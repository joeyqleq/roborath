"""Deterministic owner-managed shared per-stream AI invoke allowances."""
from __future__ import annotations

from dataclasses import dataclass
import re
import sqlite3
from typing import Iterable

OWNER_TWITCH_ID = "1414798445"
PREFIX = re.compile(r"^(?:!?ask\s*[,!:]?\s+|!rr\s+(?:ask\s+)?|(?:hey\s+)?@?roborath\s*[,!:]?\s+)", re.I)
_USER = r"@?[a-z][a-z0-9_]{2,24}"
_TARGETS = rf"({_USER}(?:\s*(?:,|and)\s*{_USER})*|every username|everyone|everybody|all(?:\s+users)?|global)"


@dataclass(frozen=True)
class InvokeIntent:
    action: str
    targets: tuple[str, ...] = ()
    amount: int | None = None


def parse(text: str) -> InvokeIntent | None:
    """Parse owner invoke controls; targets are Twitch logins or '*' sentinel."""
    value = PREFIX.sub("", str(text).strip(), count=1).strip().casefold().rstrip(".!?")
    value=re.sub(r'^please\s+|\s+please$','',value).strip()
    value=re.sub(r'\b(?:user|username)\s+(?=@?[a-z][a-z0-9_]{2,24}\b)','',value)
    # Natural owner phrasing: a gift means more uses, never a pretend LLM action.
    natural=re.fullmatch(rf'(?:give|grant)\s+(?:(\d+)\s+(?:more\s+)?(?:invokes?|invocations?|uses?)\s+to\s+|(?:permissions?|access)\s+to\s+|to\s+){_TARGETS}',value)
    if natural:return InvokeIntent('add',_parse_targets(natural[2]),int(natural[1] or 2))
    natural=re.fullmatch(rf'(?:give|grant)\s+{_TARGETS}(?:\s+(?:(\d+)\s+(?:more\s+)?(?:invokes?|invocations?|uses?)|(?:permissions?|access)))?',value)
    if natural:return InvokeIntent('add',_parse_targets(natural[1]),int(natural[2] or 2))
    natural=re.fullmatch(rf'(?:global\s+)?allow\s+{_TARGETS}(?:\s+to\s+(?:invoke|use)\s+(?:your\s+)?commands)?',value)
    if natural:return InvokeIntent('add',_parse_targets(natural[1]),2)
    match = re.fullmatch(r"global\s+(allow|turn\s+off|off|disable)", value)
    if match:
        return InvokeIntent('add',('*',),2) if match[1]=='allow' else InvokeIntent('global_off')
    match=re.fullmatch(rf'set\s+{_TARGETS}\s+(?:to\s+)?(\d+)\s+invokes?',value)
    if match:return InvokeIntent('set',_parse_targets(match[1]),int(match[2]))
    match = re.fullmatch(rf"(?:allow|grant)\s+{_TARGETS}\s+(\d+)\s+invokes?", value)
    if match:
        return InvokeIntent("set", _parse_targets(match[1]), int(match[2]))
    match = re.fullmatch(rf"(?:give|allow|grant)\s+{_TARGETS}\s+(\d+)\s+invokes?", value)
    if match:
        return InvokeIntent("set", _parse_targets(match[1]), int(match[2]))
    match = re.fullmatch(rf"add\s+(\d+)\s+invokes?\s+to\s+{_TARGETS}", value)
    if match:
        return InvokeIntent("add", _parse_targets(match[2]), int(match[1]))
    match = re.fullmatch(rf"remove\s+(\d+)\s+invokes?\s+from\s+{_TARGETS}", value)
    if match:
        return InvokeIntent("subtract", _parse_targets(match[2]), int(match[1]))
    match = re.fullmatch(rf"(?:allow|grant|give)\s+{_TARGETS}(?:\s+(?:to\s+)?(?:invoke\s+your\s+commands|all\s+ai|access))?", value)
    if match:
        return InvokeIntent("add", _parse_targets(match[1]),2)
    match = re.fullmatch(rf"(?:remove|revoke|block|deny|take\s+away)\s+{_TARGETS}(?:\s+(?:access|invoke\s+access))?", value)
    if match:
        targets = _parse_targets(match[1])
        return InvokeIntent("global_off") if targets == ("*",) else InvokeIntent("deny", targets)
    return None


def _parse_targets(value: str) -> tuple[str, ...]:
    if value in {"every username", "everyone", "everybody", "all", "all users", "global"}:
        return ("*",)
    return tuple(part.strip().lstrip("@") for part in re.split(r"\s*(?:,|\band\b)\s*", value))


class InvokeStore:
    """Transactional allowance rules; usernames must be resolved by caller.

    A `set` value is a total successful AI invokes per user per stream. An
    `add` value is a total-use increase to their current allowance. Explicit
    denials override wildcard allow rules. Administrative actions are owner-ID
    only and deduplicated by Twitch message ID.
    """

    def __init__(self, db: sqlite3.Connection, owner_id: str = OWNER_TWITCH_ID,
                 broadcaster_id: str = ""):
        if str(owner_id) and str(owner_id) != OWNER_TWITCH_ID:
            raise ValueError("configured owner ID does not match verified owner")
        self.db = db
        self.owner_id = str(owner_id or "")
        self.broadcaster_id = str(broadcaster_id or "")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS rr_invoke_rules(
          user_id TEXT PRIMARY KEY, allowed INTEGER NOT NULL,
          limit_count INTEGER NOT NULL DEFAULT -1, updated_by TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rr_invoke_limits(
          user_id TEXT NOT NULL, stream_id TEXT NOT NULL, limit_count INTEGER NOT NULL,
          updated_by TEXT NOT NULL, PRIMARY KEY(user_id,stream_id)
        );
        CREATE TABLE IF NOT EXISTS rr_invoke_global(
          singleton INTEGER PRIMARY KEY CHECK(singleton=1), enabled INTEGER NOT NULL,
          updated_by TEXT NOT NULL
        );
        INSERT OR IGNORE INTO rr_invoke_global(singleton,enabled,updated_by)
          VALUES(1,1,'system');
        CREATE TABLE IF NOT EXISTS rr_invoke_usage(
          message_id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
          stream_id TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 1,
          created_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS rr_invoke_usage_scope
          ON rr_invoke_usage(user_id,stream_id,used);
        CREATE TABLE IF NOT EXISTS rr_invoke_audit(
          message_id TEXT PRIMARY KEY, actor_id TEXT NOT NULL,
          action TEXT NOT NULL, targets TEXT NOT NULL, amount INTEGER,
          stream_id TEXT NOT NULL, created_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """)

    def apply(self, actor_id: str, message_id: str, targets: Iterable[str],
              action: str, amount: int | None = None, stream_id: str = "") -> bool:
        if not self.owner_id or str(actor_id) != self.owner_id:
            raise PermissionError("only verified owner can manage invoke access")
        if not message_id:
            raise ValueError("message ID required for idempotent controls")
        target_list = tuple(str(t) for t in targets)
        if action not in {"allow", "deny", "set", "add", "subtract", "global_allow", "global_off"}:
            raise ValueError("unsupported invoke action")
        if action not in {"global_allow", "global_off"}:
            if not target_list or any(t != "*" and not t.isdigit() for t in target_list):
                raise ValueError("targets must be resolved numeric Twitch IDs")
            if "*" in target_list and len(target_list) != 1:
                raise ValueError("wildcard must be the only target")
        if action in {"set", "add", "subtract"} and (amount is None or amount < 0 or amount > 10000):
            raise ValueError("invoke amount must be between 0 and 10000")
        if action in {"allow", "deny"}:
            amount = 0
        self.db.execute("BEGIN IMMEDIATE")
        try:
            cur = self.db.execute("INSERT OR IGNORE INTO rr_invoke_audit(message_id,actor_id,action,targets,amount,stream_id) VALUES(?,?,?,?,?,?)",
                                  (message_id, str(actor_id), action, ",".join(target_list), amount, str(stream_id)))
            if not cur.rowcount:
                self.db.rollback()
                return False
            if action in {"global_allow", "global_off"}:
                self.db.execute("UPDATE rr_invoke_global SET enabled=?,updated_by=? WHERE singleton=1",
                                (int(action == "global_allow"), str(actor_id)))
                if action == "global_allow":
                    self.db.execute("INSERT INTO rr_invoke_rules(user_id,allowed,limit_count,updated_by) VALUES('*',1,-1,?) ON CONFLICT(user_id) DO UPDATE SET allowed=1,limit_count=-1,updated_by=excluded.updated_by", (str(actor_id),))
            else:
                # A fresh global allowance explicitly reopens the non-owner gate.
                if target_list==('*',) and action in ('set','add','allow'):
                    self.db.execute('UPDATE rr_invoke_global SET enabled=1,updated_by=? WHERE singleton=1',(str(actor_id),))
                for target in target_list:
                    prior = self.db.execute("SELECT limit_count FROM rr_invoke_limits WHERE user_id=? AND stream_id=?", (target,str(stream_id))).fetchone()
                    if prior is None and target != "*":
                        prior = self.db.execute("SELECT limit_count FROM rr_invoke_limits WHERE user_id='*' AND stream_id=?", (str(stream_id),)).fetchone()
                    base = self.db.execute("SELECT limit_count FROM rr_invoke_rules WHERE user_id=?", (target,)).fetchone()
                    if base is None:
                        base = self.db.execute("SELECT limit_count FROM rr_invoke_rules WHERE user_id='*'").fetchone()
                    if action == "deny":
                        allowed, limit = 0, 0
                    elif action == "allow":
                        allowed, limit = 1, -1
                    elif action == "set":
                        allowed, limit = 1, int(amount)
                    elif action == "add":
                        allowed, limit = 1, (int(prior[0]) if prior else 0) + int(amount)
                    else:
                        allowed, limit = 1, max(0, (int(prior[0]) if prior else int(base[0]) if base else 0) - int(amount))
                    base_limit = (-1 if action == "allow" or (base and int(base[0]) < 0)
                                  else 0 if action in {"set", "add", "subtract"} else limit)
                    self.db.execute("INSERT INTO rr_invoke_rules(user_id,allowed,limit_count,updated_by) VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET allowed=excluded.allowed,limit_count=excluded.limit_count,updated_by=excluded.updated_by",
                                    (target, allowed, base_limit, str(actor_id)))
                    if action in {"allow", "deny"}:
                        self.db.execute("DELETE FROM rr_invoke_limits WHERE user_id=? AND stream_id=?", (target,str(stream_id)))
                    else:
                        self.db.execute("INSERT INTO rr_invoke_limits(user_id,stream_id,limit_count,updated_by) VALUES(?,?,?,?) ON CONFLICT(user_id,stream_id) DO UPDATE SET limit_count=excluded.limit_count,updated_by=excluded.updated_by", (target,str(stream_id),limit,str(actor_id)))
            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            raise

    def access(self, user_id: str) -> bool | None:
        """True/False for explicit shared/wildcard policy; None for legacy policy."""
        if self.owner_id and str(user_id) == self.owner_id:
            return True
        enabled = self.db.execute("SELECT enabled FROM rr_invoke_global WHERE singleton=1").fetchone()
        if not enabled or not enabled[0]:
            return False
        row = self.db.execute("SELECT allowed FROM rr_invoke_rules WHERE user_id=?", (str(user_id),)).fetchone()
        if row is not None:
            return bool(row[0])
        wildcard = self.db.execute("SELECT allowed FROM rr_invoke_rules WHERE user_id='*'").fetchone()
        return bool(wildcard[0]) if wildcard is not None else None

    def limit(self, user_id: str, stream_id: str) -> int | None:
        if self.access(user_id) is None:
            return None
        if (self.owner_id and str(user_id) == self.owner_id) or (self.broadcaster_id and str(user_id) == self.broadcaster_id):
            return None
        row = self.db.execute("SELECT limit_count FROM rr_invoke_rules WHERE user_id=?", (str(user_id),)).fetchone()
        if row is None:
            row = self.db.execute("SELECT limit_count FROM rr_invoke_rules WHERE user_id='*'").fetchone()
        scoped = self.db.execute("SELECT limit_count FROM rr_invoke_limits WHERE user_id IN (?, '*') AND stream_id=? ORDER BY CASE user_id WHEN ? THEN 0 ELSE 1 END LIMIT 1", (str(user_id),str(stream_id),str(user_id))).fetchone()
        if scoped:return int(scoped[0])
        # A numeric allowance applies only to the named stream. Outside that
        # stream, the bridge's existing fact/research quotas apply.
        return -1 if row and int(row[0]) < 0 else None

    def reserve(self, user_id: str, message_id: str, stream_id: str) -> bool:
        uid, mid, stream = str(user_id), str(message_id), str(stream_id)
        if not mid or not stream:
            return False
        if self.owner_id and uid == self.owner_id:
            return True
        if self.broadcaster_id and uid == self.broadcaster_id:
            return self.access(uid) is not False
        access = self.access(uid)
        if access is False:
            return False
        limit = self.limit(uid, stream)
        if limit is None:
            return access is not False
        if limit < 0:
            return True
        if limit == 0:
            return False
        self.db.execute("BEGIN IMMEDIATE")
        try:
            used = self.db.execute("SELECT COUNT(*) FROM rr_invoke_usage WHERE user_id=? AND stream_id=? AND used=1", (uid, stream)).fetchone()[0]
            if used >= limit:
                self.db.rollback()
                return False
            cur = self.db.execute("INSERT OR IGNORE INTO rr_invoke_usage(message_id,user_id,stream_id,used) VALUES(?,?,?,1)", (mid, uid, stream))
            if not cur.rowcount:
                self.db.rollback()
                return False
            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            raise

    def refund(self, message_id: str) -> None:
        with self.db:
            self.db.execute("UPDATE rr_invoke_usage SET used=0 WHERE message_id=?", (str(message_id),))

    def forget(self, user_id: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM rr_invoke_usage WHERE user_id=?", (str(user_id),))
            self.db.execute("DELETE FROM rr_invoke_rules WHERE user_id=?", (str(user_id),))
            self.db.execute("DELETE FROM rr_invoke_limits WHERE user_id=?", (str(user_id),))

    def prune(self, days: int = 30) -> None:
        days = max(1, min(int(days), 30))
        with self.db:
            self.db.execute("DELETE FROM rr_invoke_usage WHERE created_utc < datetime('now', ?)", (f"-{days} days",))

    def status(self, stream_id: str | None = None) -> dict:
        global_row = self.db.execute("SELECT enabled FROM rr_invoke_global WHERE singleton=1").fetchone()
        rules = self.db.execute("SELECT user_id,allowed,limit_count FROM rr_invoke_rules ORDER BY user_id").fetchall()
        if stream_id is None:
            usage = self.db.execute("SELECT stream_id,user_id,COUNT(*) FROM rr_invoke_usage WHERE used=1 GROUP BY stream_id,user_id ORDER BY stream_id,user_id").fetchall()
        else:
            usage = self.db.execute("SELECT stream_id,user_id,COUNT(*) FROM rr_invoke_usage WHERE used=1 AND stream_id=? GROUP BY stream_id,user_id ORDER BY user_id", (str(stream_id),)).fetchall()
        return {"global_enabled": bool(global_row and global_row[0]), "rules": rules, "usage": usage}
