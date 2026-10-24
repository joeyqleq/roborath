"""Persistent least-privilege quotas and grants for public Twitch commands.

Security properties: immutable Twitch user IDs only, atomic quota consumption,
message-ID idempotence, owner-only delegation, and no Twitch moderator assumption.
"""
from __future__ import annotations
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

BASE_LIMITS = {"fact": 2, "research": 1}
SUPERVISOR_CAPABILITIES = {"fact_grant", "research_grant", "mario_manage", "trigger_manage"}
PUBLIC_CAPABILITIES = {"fact", "research", "mario_read", "help"}

@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    remaining: int | None = None

def utc_day(when: datetime | None = None) -> str:
    now = when or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("timezone-aware datetime required")
    return now.astimezone(timezone.utc).date().isoformat()

def parse_public(text: str):
    """Strict invocation avoids triggering on rath's name, cheers or quoted bot."""
    text = text.strip()
    pattern = r"^(?:!fact|!check|!research|!rr\s+(?:fact|check|research)|@roborath\s+(?:fact|check|research)|(?:hey\s+)?roborath\s*[,!:]\s*(?:fact|check|research))(?=\s|$)"
    m = re.match(pattern, text, re.IGNORECASE)
    if not m:
        return None
    verb = m.group().lower()
    capability = "research" if "research" in verb else "fact"
    question = text[m.end():].strip()
    if not question:
        return None
    return capability, question[:700]

class PolicyStore:
    def __init__(self, db: sqlite3.Connection, owner_id: str, broadcaster_id: str):
        self.db = db
        # Never accept usernames for privileged identities.
        self.owner_id = self._require_id(owner_id)
        self.broadcaster_id = self._require_id(broadcaster_id)
        self.db.execute("""CREATE TABLE IF NOT EXISTS rr_consumptions(
           message_id TEXT PRIMARY KEY, twitch_user_id TEXT NOT NULL,
           capability TEXT NOT NULL, scope TEXT NOT NULL, used_utc TEXT NOT NULL
        )""")
        self.db.execute("""CREATE INDEX IF NOT EXISTS rr_quotas_idx
           ON rr_consumptions(twitch_user_id,capability,scope)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS rr_grants(
           user_id TEXT NOT NULL, capability TEXT NOT NULL,
           scope TEXT NOT NULL, extra INTEGER NOT NULL DEFAULT 0,
           PRIMARY KEY(user_id,capability,scope)
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS rr_supervisors(
           user_id TEXT NOT NULL, capability TEXT NOT NULL,
           granted_by TEXT NOT NULL,
           PRIMARY KEY(user_id,capability)
        )""")
        self.db.commit()

    @staticmethod
    def _require_id(value: str) -> str:
        value = str(value).strip()
        if not re.fullmatch(r"[0-9]{1,25}", value):
            raise ValueError("owner/broadcaster IDs must be verified numeric Twitch IDs")
        return value

    def is_owner(self, actor_id: str) -> bool:
        return actor_id == self.owner_id

    def can_manage(self, actor_id: str, capability: str) -> bool:
        if self.is_owner(actor_id):
            return True
        if capability not in SUPERVISOR_CAPABILITIES:
            return False
        return self.db.execute(
            "SELECT 1 FROM rr_supervisors WHERE user_id=? AND capability=?",
            (actor_id, capability)
        ).fetchone() is not None

    def delegate(self, actor_id: str, target_id: str, capability: str, enabled=True):
        """Only verified owner can install/revoke bounded persistent permissions."""
        if not self.is_owner(actor_id):
            raise PermissionError("only owner can delegate")
        target_id = self._require_id(target_id)
        if capability not in SUPERVISOR_CAPABILITIES:
            raise ValueError("capability is not delegable")
        with self.db:
            if enabled:
                self.db.execute("""INSERT OR REPLACE INTO rr_supervisors
                   (user_id,capability,granted_by) VALUES(?,?,?)""",
                   (target_id,capability,actor_id))
            else:
                self.db.execute("""DELETE FROM rr_supervisors
                   WHERE user_id=? AND capability=?""",(target_id,capability))

    def scope(self, capability: str, stream_id: str, day: str | None = None):
        if capability == "fact":
            # Offline-day buckets do NOT represent a completed live stream.
            if not stream_id:
                raise ValueError("stream ID required for facts")
            return "stream:" + stream_id
        if capability == "research":
            return "day:" + (day or utc_day())
        raise ValueError("unsupported capability")

    def grant_extra(self, actor_id: str, target_id: str, capability: str,
                    scope: str, amount: int):
        target_id = self._require_id(target_id)
        if capability not in BASE_LIMITS:
            raise ValueError("unsupported grant")
        role = capability + "_grant"
        if not self.can_manage(actor_id, role):
            raise PermissionError("no permission to grant this quota")
        if not 1 <= amount <= 20:
            raise ValueError("one grant may add only 1..20 uses")
        with self.db:
            self.db.execute("""INSERT INTO rr_grants(user_id,capability,scope,extra)
             VALUES(?,?,?,?) ON CONFLICT(user_id,capability,scope)
             DO UPDATE SET extra=extra+excluded.extra""",
             (target_id,capability,scope,amount))

    def check_or_reserve(self, user_id: str, message_id: str,
                         capability: str, stream_id: str, day: str | None = None) -> Decision:
        if capability not in BASE_LIMITS:
            return Decision(False,"unsupported command")
        if not message_id or not user_id:
            return Decision(False,"missing verified message identity")
        if user_id in (self.owner_id, self.broadcaster_id):
            return Decision(True,"owner/broadcaster unlimited")
        scope = self.scope(capability,stream_id,day)
        # A transaction prevents concurrent commands bypassing quota.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            prior = self.db.execute(
                "SELECT 1 FROM rr_consumptions WHERE message_id=?", (message_id,)
            ).fetchone()
            if prior:
                self.db.rollback()
                return Decision(False, "duplicate command")
            spent = self.db.execute("""SELECT COUNT(*) FROM rr_consumptions
                WHERE twitch_user_id=? AND capability=? AND scope=?""",
                (user_id,capability,scope)).fetchone()[0]
            added = self.db.execute("""SELECT extra FROM rr_grants
                WHERE user_id=? AND capability=? AND scope=?""",
                (user_id,capability,scope)).fetchone()
            limit = BASE_LIMITS[capability] + (added[0] if added else 0)
            if spent >= limit:
                self.db.rollback()
                return Decision(False, "limit reached; ask a RoboRath supervisor for more", 0)
            self.db.execute("""INSERT INTO rr_consumptions
               (message_id,twitch_user_id,capability,scope,used_utc)
               VALUES(?,?,?,?,?)""",
               (message_id,user_id,capability,scope,datetime.now(timezone.utc).isoformat()))
            self.db.commit()
            return Decision(True,"allowed",limit-spent-1)
        except Exception:
            self.db.rollback()
            raise

    def refund(self, message_id: str):
        """Return allowance if downstream AI or Twitch delivery failed."""
        with self.db:
            self.db.execute("DELETE FROM rr_consumptions WHERE message_id=?", (message_id,))

    def forget(self, user_id: str):
        with self.db:
            self.db.execute("DELETE FROM rr_consumptions WHERE twitch_user_id=?", (user_id,))
            self.db.execute("DELETE FROM rr_grants WHERE user_id=?", (user_id,))
            self.db.execute("DELETE FROM rr_supervisors WHERE user_id=?", (user_id,))
