"""Persistent, bounded public-text watches, reminders, and stream timers.

No shell/tool execution is possible from a rule. Callers must apply mute, owner-only
QA, offline, and permission checks immediately before posting any returned message.
"""
from __future__ import annotations
import re
import sqlite3
from datetime import datetime, timezone, timedelta


def utc_now():
    return datetime.now(timezone.utc)


def _public_text(value, limit):
    text = re.sub(r"\s+", " ", str(value)).strip()
    text = "".join(ch for ch in text if ch >= " " and ch != "\x7f")
    return text[:limit]

def _iso(value):
    if value.tzinfo is None:
        raise ValueError("timezone-aware UTC time required")
    return value.astimezone(timezone.utc).isoformat()


def _parse_when(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValueError("use an ISO timestamp with a UTC offset") from None
    if parsed.tzinfo is None:
        raise ValueError("fixed reminder time must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def parse_duration(text):
    match = re.fullmatch(r"(\d{1,4})(m|h|d)", str(text).lower())
    if not match:
        return None
    n = int(match.group(1))
    seconds = n * {"m": 60, "h": 3600, "d": 86400}[match.group(2)]
    return seconds if 60 <= seconds <= 7 * 86400 else None


def _whole_phrase(phrase):
    """Case/punctuation tolerant whole-word phrase pattern."""
    words = re.findall(r"[\w]+", phrase, flags=re.UNICODE)
    if not words:
        raise ValueError("phrase needs at least one letter or number")
    return re.compile(r"(?<!\w)" + r"[^\w]+".join(map(re.escape, words)) + r"(?!\w)", re.UNICODE)


FOLLOW_BANK = (
    "Twenty minutes in, you magnificent chaos merchants. If Rath's nonsense is growing on you, hit Follow.",
    "The revolution can wait ten seconds. Follow Rathbone before you forget why you came here.",
    "Hey goyim, the Follow button isn't going to organize itself. Give Rath some love.",
    "If this stream has improved your life by even one questionable decision, follow Rathbone.",
    "Follow Rath now. Your future self will thank you, or at least stop asking where the stream went.",
    "A little Follow for Rathbone keeps this beautiful circus legally classified as a community.",
    "Enjoying the stream? Follow Rath before the algorithm buries us under crypto podcasts.",
    "Tap Follow and help Rathbone's tiny corner of the internet evade corporate obscurity.",
    "This is your periodic reminder to follow Rath: the only button here with revolutionary potential.",
    "Rath's still causing a scene. Follow if you'd like a notification next time the evidence gets weird.",
    "Follow Rathbone. It's free, unlike the emotional cost of watching this race.",
    "You found the stream; now make it a recurring bad decision. Hit Follow.",
    "A follow for Rath keeps the channel alive and the chat's standards comfortably underground.",
    "If you're still here, the Follow button and you should probably talk.",
    "Follow Rathbone for future broadcasts, fresh chaos, and absolutely no corporate mission statement.",
    "Follow Rath before your recommendations feed gets ideas above its station.",
    "A follow now means Twitch may tell you when Rath is live. The platform occasionally earns its keep.",
    "Still watching? Commit to the bit: follow Rathbone and return for more questionable analysis.",
    "Follow Rath. No subscription required, no blood oath, no venture-capital pitch.",
    "Tell the algorithm this stream deserves oxygen. Hit Follow for Rathbone.",
    "Follow Rath and help this chat remain a tiny, beautifully dysfunctional institution.",
    "Rath is live now; follow to catch the next chapter of this avoidable saga.",
    "The stream survives on your attention and the occasional follow. Choose your weapon.",
    "Follow Rathbone if you'd like Twitch to remember you enjoy this particular nonsense.",
    "Follow now; future you can decide whether this was a wise use of a notification.",
    "One small follow for you, one statistically insignificant but emotionally useful signal for Rath.",
    "If the chaos is working, follow Rath. If it isn't, follow anyway and file a complaint in chat.",
    "Follow Rathbone. The channel's growth strategy remains less coherent than the stream.",
    "A follow keeps Rath on your radar without requiring a corporate loyalty oath.",
    "Follow Rathbone for the next stream; even this algorithm can learn a little solidarity.",
)


class Notifications:
    def __init__(self, db: sqlite3.Connection, owner_id: str | None = None):
        self.db = db
        self.owner_id = str(owner_id) if owner_id is not None else None
        self.db.execute("""CREATE TABLE IF NOT EXISTS rr_reminders(
           id INTEGER PRIMARY KEY AUTOINCREMENT, twitch_user_id TEXT NOT NULL,
           stream_id TEXT NOT NULL, message TEXT NOT NULL,
           due_utc TEXT NOT NULL, delivered_utc TEXT, cancelled_utc TEXT
        )""")
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(rr_reminders)")}
        if "cancelled_utc" not in cols:
            self.db.execute("ALTER TABLE rr_reminders ADD COLUMN cancelled_utc TEXT")
        self.db.execute("CREATE INDEX IF NOT EXISTS rr_reminders_due ON rr_reminders(due_utc,delivered_utc,cancelled_utc)")
        self.db.execute("""CREATE TABLE IF NOT EXISTS rr_text_watches(
           id INTEGER PRIMARY KEY AUTOINCREMENT, twitch_user_id TEXT NOT NULL,
           stream_id TEXT NOT NULL, phrase TEXT NOT NULL,
           response TEXT NOT NULL, expires_utc TEXT NOT NULL,
           fired_utc TEXT, enabled INTEGER NOT NULL DEFAULT 1
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS rr_automation_rules(
           id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id TEXT NOT NULL,
           name TEXT NOT NULL, phrase TEXT NOT NULL, response TEXT NOT NULL,
           whole_word INTEGER NOT NULL DEFAULT 1, enabled INTEGER NOT NULL DEFAULT 1,
           cooldown_seconds INTEGER NOT NULL DEFAULT 300, expires_utc TEXT,
           fired_utc TEXT, UNIQUE(owner_id,name)
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS rr_first_chat_seen(
           stream_id TEXT NOT NULL, twitch_user_id TEXT NOT NULL,
           message_id TEXT NOT NULL, login TEXT NOT NULL, seen_utc TEXT NOT NULL,
           PRIMARY KEY(stream_id,twitch_user_id)
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS rr_stream_promotions(
           stream_id TEXT PRIMARY KEY, started_utc TEXT NOT NULL,
           last_tick INTEGER NOT NULL DEFAULT 0, ended_utc TEXT,
           used_promotions TEXT NOT NULL DEFAULT ''
        )""")
        promo_cols = {r[1] for r in self.db.execute("PRAGMA table_info(rr_stream_promotions)")}
        if "used_promotions" not in promo_cols:
            self.db.execute("ALTER TABLE rr_stream_promotions ADD COLUMN used_promotions TEXT NOT NULL DEFAULT ''")
        self.db.execute("CREATE TABLE IF NOT EXISTS rr_rule_delivery(singleton INTEGER PRIMARY KEY CHECK(singleton=1),last_utc TEXT)")
        self.db.execute("INSERT OR IGNORE INTO rr_rule_delivery(singleton,last_utc) VALUES(1,NULL)")
        self.db.execute("""CREATE TABLE IF NOT EXISTS rr_welcome_config(
          owner_id TEXT PRIMARY KEY, response TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS rr_automation_controls(
          message_id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, ack TEXT, created_utc TEXT NOT NULL
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS rr_processed_automation_messages(
          stream_id TEXT NOT NULL, message_id TEXT NOT NULL, created_utc TEXT NOT NULL,
          PRIMARY KEY(stream_id,message_id)
        )""")
        self.db.commit()

    def add_reminder(self, user, stream, delay, text, now=None):
        seconds = parse_duration(delay)
        if seconds is None:
            raise ValueError("use 1m-7d, e.g. 20m or 2h")
        return self.add_reminder_at(user, stream, (now or utc_now()) + timedelta(seconds=seconds), text, now=now)

    def add_reminder_at(self, user, stream, due, text, now=None):
        message = _public_text(text, 240)
        if not message:
            raise ValueError("reminder text required")
        when = now or utc_now()
        due = due if isinstance(due, datetime) else _parse_when(due)
        due = due.astimezone(timezone.utc)
        if due <= when or due > when + timedelta(days=7):
            raise ValueError("reminder must be in the next 7 days")
        pending = self.db.execute("SELECT COUNT(*) FROM rr_reminders WHERE twitch_user_id=? AND delivered_utc IS NULL AND cancelled_utc IS NULL", (user,)).fetchone()[0]
        total = self.db.execute("SELECT COUNT(*) FROM rr_reminders WHERE delivered_utc IS NULL AND cancelled_utc IS NULL").fetchone()[0]
        if pending >= 5:
            raise ValueError("5 outstanding reminders max per user")
        if total >= 50:
            raise ValueError("reminder queue is full")
        with self.db:
            cur = self.db.execute("INSERT INTO rr_reminders(twitch_user_id,stream_id,message,due_utc) VALUES(?,?,?,?)", (str(user), str(stream or ""), message, _iso(due)))
            return cur.lastrowid

    def due(self, now=None, limit=5):
        when = _iso(now or utc_now())
        return self.db.execute("SELECT id,twitch_user_id,message FROM rr_reminders WHERE delivered_utc IS NULL AND cancelled_utc IS NULL AND due_utc<=? ORDER BY due_utc ASC LIMIT ?", (when, min(max(1, int(limit)), 10))).fetchall()

    def delivered(self, ident, now=None):
        with self.db:
            self.db.execute("UPDATE rr_reminders SET delivered_utc=? WHERE id=? AND delivered_utc IS NULL AND cancelled_utc IS NULL", (_iso(now or utc_now()), ident))

    def list_reminders(self, actor_id, owner=False, limit=10):
        is_owner = self.owner_id is not None and str(actor_id) == self.owner_id
        if owner and not is_owner:
            raise PermissionError("only the verified owner may inspect all reminders")
        if is_owner:
            rows = self.db.execute("SELECT id,twitch_user_id,message,due_utc FROM rr_reminders WHERE delivered_utc IS NULL AND cancelled_utc IS NULL ORDER BY due_utc LIMIT ?", (min(max(1, limit), 50),))
        else:
            rows = self.db.execute("SELECT id,twitch_user_id,message,due_utc FROM rr_reminders WHERE twitch_user_id=? AND delivered_utc IS NULL AND cancelled_utc IS NULL ORDER BY due_utc LIMIT ?", (str(actor_id), min(max(1, limit), 50)))
        return rows.fetchall()

    def cancel_reminder(self, ident, actor_id, now=None, owner=False):
        is_owner = self.owner_id is not None and str(actor_id) == self.owner_id
        if owner and not is_owner:
            raise PermissionError("only the verified owner may cancel another viewer's reminder")
        with self.db:
            cur = self.db.execute("UPDATE rr_reminders SET cancelled_utc=? WHERE id=? AND delivered_utc IS NULL AND cancelled_utc IS NULL AND (? OR twitch_user_id=?)", (_iso(now or utc_now()), int(ident), int(is_owner), str(actor_id)))
            return cur.rowcount == 1

    def watch(self, user, stream, phrase, response, now=None):
        phrase = _public_text(phrase, 80).lower()
        response = _public_text(response, 180)
        if len(phrase) < 3 or not response:
            raise ValueError("watch phrase and response required")
        active = self.db.execute("SELECT COUNT(*) FROM rr_text_watches WHERE twitch_user_id=? AND enabled=1 AND expires_utc>?", (user, _iso(now or utc_now()))).fetchone()[0]
        if active >= 3:
            raise ValueError("3 active watches max")
        expires = (now or utc_now()) + timedelta(hours=12)
        with self.db:
            cur = self.db.execute("INSERT INTO rr_text_watches(twitch_user_id,stream_id,phrase,response,expires_utc) VALUES(?,?,?,?,?)", (user, stream, phrase, response, _iso(expires)))
        return cur.lastrowid

    def add_rule(self, actor_id, name, phrase, response, *, whole_word=True, cooldown_seconds=300, now=None):
        owner = str(self.owner_id or "")
        if not owner or str(actor_id) != owner:
            raise PermissionError("only the verified owner can manage stream rules")
        name, phrase, response = str(name).strip().casefold()[:40], _public_text(phrase, 80), _public_text(response, 180)
        if not re.fullmatch(r"[\w -]{1,40}", name) or not phrase or not response:
            raise ValueError("give the rule a short name, phrase, and response")
        _whole_phrase(phrase)
        cooldown_seconds = int(cooldown_seconds)
        if cooldown_seconds < 60 or cooldown_seconds > 86400:
            raise ValueError("rule cooldown must be 1m-24h")
        count = self.db.execute("SELECT COUNT(*) FROM rr_automation_rules WHERE owner_id=?", (owner,)).fetchone()[0]
        exists = self.db.execute("SELECT 1 FROM rr_automation_rules WHERE owner_id=? AND name=? COLLATE NOCASE", (owner, name)).fetchone()
        if count >= 20 and not exists:
            raise ValueError("20 active rules max")
        with self.db:
            self.db.execute("INSERT INTO rr_automation_rules(owner_id,name,phrase,response,whole_word,cooldown_seconds) VALUES(?,?,?,?,?,?) ON CONFLICT(owner_id,name) DO UPDATE SET phrase=excluded.phrase,response=excluded.response,whole_word=excluded.whole_word,cooldown_seconds=excluded.cooldown_seconds,enabled=1", (owner, name, phrase, response, int(bool(whole_word)), cooldown_seconds))
        return name

    def manage_rule(self, actor_id, action, name, *, sample_text=None):
        owner = str(self.owner_id or "")
        if not owner or str(actor_id) != owner:
            raise PermissionError("only the verified owner can manage stream rules")
        action = action.casefold()
        if action == "list":
            return self.db.execute("SELECT name,phrase,response,whole_word,enabled,cooldown_seconds FROM rr_automation_rules WHERE owner_id=? ORDER BY name", (owner,)).fetchall()
        if action == "test":
            row = self.db.execute("SELECT phrase,whole_word FROM rr_automation_rules WHERE owner_id=? AND name=? COLLATE NOCASE", (owner, name)).fetchone()
            if not row:
                raise ValueError("rule not found")
            if sample_text is None:
                return row
            return bool(_whole_phrase(row[0].casefold()).search(str(sample_text).casefold())) if row[1] else row[0].casefold() in str(sample_text).casefold()
        if action not in {"enable", "disable", "remove"}:
            raise ValueError("use list, test, enable, disable, or remove")
        with self.db:
            if action == "remove":
                cur = self.db.execute("DELETE FROM rr_automation_rules WHERE owner_id=? AND name=? COLLATE NOCASE", (owner, name))
            else:
                cur = self.db.execute("UPDATE rr_automation_rules SET enabled=? WHERE owner_id=? AND name=? COLLATE NOCASE", (int(action == "enable"), owner, name))
        if cur.rowcount != 1:
            raise ValueError("rule not found")
        return True

    def scan_rules(self, stream, message_id, text, now=None, limit=1):
        """Scan deterministic owner-created rules; caller enforces send guardrails."""
        when = now or utc_now()
        rows = self.db.execute("SELECT id,name,phrase,response,whole_word,cooldown_seconds,fired_utc FROM rr_automation_rules WHERE enabled=1 AND (expires_utc IS NULL OR expires_utc>?) ORDER BY id LIMIT 100", (_iso(when),)).fetchall()
        global_last = self.db.execute("SELECT last_utc FROM rr_rule_delivery WHERE singleton=1").fetchone()[0]
        if global_last and _parse_when(global_last) > when - timedelta(minutes=1):
            return []
        out = []
        body = str(text)
        for ident, name, phrase, response, whole_word, cooldown, fired in rows:
            matched = bool(_whole_phrase(phrase.casefold()).search(body.casefold())) if whole_word else phrase.casefold() in body.casefold()
            if not matched or (fired and _parse_when(fired) > when - timedelta(seconds=cooldown)):
                continue
            out.append((ident, name, response))
            if len(out) >= max(1, min(5, limit)):
                break
        if out:
            with self.db:
                self.db.executemany("UPDATE rr_automation_rules SET fired_utc=? WHERE id=?", [(_iso(when), row[0]) for row in out])
                self.db.execute("UPDATE rr_rule_delivery SET last_utc=? WHERE singleton=1", (_iso(when),))
        return out

    def first_chat(self, stream_id, user_id, login, message_id, now=None):
        """Persist first observed message once per immutable ID in each stream."""
        if not stream_id or not str(user_id).isdigit() or not message_id:
            return False
        with self.db:
            cur = self.db.execute("INSERT OR IGNORE INTO rr_first_chat_seen(stream_id,twitch_user_id,message_id,login,seen_utc) VALUES(?,?,?,?,?)", (str(stream_id), str(user_id), str(message_id), str(login)[:25], _iso(now or utc_now())))
        return cur.rowcount == 1

    def start_stream(self, stream_id, started_utc=None):
        if not stream_id:
            raise ValueError("verified live stream ID required")
        started = started_utc or utc_now()
        with self.db:
            self.db.execute("INSERT INTO rr_stream_promotions(stream_id,started_utc,last_tick,ended_utc) VALUES(?,?,0,NULL) ON CONFLICT(stream_id) DO UPDATE SET started_utc=excluded.started_utc,ended_utc=NULL WHERE rr_stream_promotions.ended_utc IS NOT NULL", (str(stream_id), _iso(started)))

    def end_stream(self, stream_id, now=None):
        with self.db:
            self.db.execute("UPDATE rr_stream_promotions SET ended_utc=? WHERE stream_id=? AND ended_utc IS NULL", (_iso(now or utc_now()), str(stream_id)))

    def follow_tick(self, stream_id, now=None, *, live, muted=False, owner_only=False):
        """Return one hand-written prompt for the latest elapsed 20m tick.

        Missed ticks are skipped, never replayed in a burst after restart. A blocked
        tick is consumed too, so mute/QA/offline transitions cannot cause catch-up.
        """
        when = now or utc_now()
        row = self.db.execute("SELECT started_utc,last_tick,ended_utc,used_promotions FROM rr_stream_promotions WHERE stream_id=?", (str(stream_id),)).fetchone()
        if not row or row[2]:
            return None
        elapsed = int((_parse_when(_iso(when)) - _parse_when(row[0])).total_seconds() // 1200)
        if elapsed <= row[1] or elapsed < 1:
            return None
        tick = elapsed
        used = {int(v) for v in row[3].split(",") if v}
        available = [i for i in range(len(FOLLOW_BANK)) if i not in used]
        index = available[(tick - 1) % len(available)] if available else None
        with self.db:
            allowed = live and not muted and not owner_only
            next_used = row[3] if index is None or not allowed else ",".join((row[3].split(",") if row[3] else []) + [str(index)])
            cur = self.db.execute("UPDATE rr_stream_promotions SET last_tick=?,used_promotions=? WHERE stream_id=? AND last_tick=? AND ended_utc IS NULL", (tick, next_used, str(stream_id), row[1]))
            if cur.rowcount != 1 or index is None or not allowed:
                return None
        return FOLLOW_BANK[index]

    def scan(self, stream, text, now=None, limit=1):
        """Return max one legacy watch alert; five-minute cooldown, same stream."""
        when = now or utc_now()
        rows = self.db.execute("SELECT id,twitch_user_id,phrase,response,fired_utc FROM rr_text_watches WHERE stream_id=? AND enabled=1 AND expires_utc>? ORDER BY id LIMIT 100", (stream, _iso(when))).fetchall()
        fired = []
        for ident, user, phrase, response, last in rows:
            if phrase not in str(text).casefold():
                continue
            if last and _parse_when(last) > when - timedelta(minutes=5):
                continue
            fired.append((ident, user, response))
            if len(fired) >= limit:
                break
        for ident, user, response in fired:
            with self.db:
                self.db.execute("UPDATE rr_text_watches SET fired_utc=? WHERE id=?", (_iso(when), ident))
        return fired

    def set_welcome(self, actor_id, response=None, enabled=True):
        if self.owner_id is None or str(actor_id) != self.owner_id:
            raise PermissionError("only the verified owner can configure first-chat welcomes")
        if enabled:
            message = _public_text(response or "", 180)
            if not message:
                raise ValueError("welcome response required")
            with self.db:
                self.db.execute("INSERT INTO rr_welcome_config(owner_id,response,enabled) VALUES(?,?,1) ON CONFLICT(owner_id) DO UPDATE SET response=excluded.response,enabled=1", (self.owner_id, message))
        else:
            with self.db:
                self.db.execute("UPDATE rr_welcome_config SET enabled=0 WHERE owner_id=?", (self.owner_id,))

    def process_chat(self, stream_id, user_id, login, message_id, text, *, live=True, muted=False, owner_only=False, now=None):
        """Return at most one welcome/rule response for a newly seen public message.

        Caller must invoke this after its public-chat/opt-out collector checks and
        recheck mute/QA/access immediately before sending each returned response.
        """
        if not live or not stream_id or not message_id or not str(user_id).isdigit():
            return []
        when = now or utc_now()
        with self.db:
            cur = self.db.execute("INSERT OR IGNORE INTO rr_processed_automation_messages(stream_id,message_id,created_utc) VALUES(?,?,?)", (str(stream_id), str(message_id), _iso(when)))
        if cur.rowcount != 1:
            return []
        first = self.first_chat(stream_id, user_id, login, message_id, when)
        if muted or owner_only:
            return []
        if first:
            row = self.db.execute("SELECT response,enabled FROM rr_welcome_config WHERE owner_id=?", (self.owner_id or "",)).fetchone()
            last = self.db.execute("SELECT last_utc FROM rr_rule_delivery WHERE singleton=1").fetchone()[0]
            if row and row[1] and (not last or _parse_when(last) <= when-timedelta(minutes=1)):
                with self.db:
                    self.db.execute("UPDATE rr_rule_delivery SET last_utc=? WHERE singleton=1", (_iso(when),))
                return [row[0]]
        rules = self.scan_rules(stream_id, message_id, text, when, limit=1)
        alerts = [r[2] for r in rules]
        legacy = self.scan(stream_id, text, when, limit=1) if not alerts else []
        if legacy:
            alerts.append(legacy[0][2])
        return alerts[:1]

    def handle_control(self, text, actor_id, stream_id="", message_id="", now=None):
        """Execute owner rule controls and reminder list/cancel commands idempotently.

        Acknowledgments contain only fixed local text or owner supplied bounded text;
        the caller handles routing and final mute/QA authorization before sending.
        """
        value = str(text).strip()
        control = parse_automation_control(value)
        remind = re.fullmatch(r"(?i)!rr\s+remind(?:\s+(\d{1,4}[mhd])|\s+at\s+(\S+))\s+(.+)", value)
        list_reminders = re.fullmatch(r"(?i)!rr\s+reminders?(?:\s+list)?", value)
        cancel = re.fullmatch(r"(?i)!rr\s+reminder\s+cancel\s+(\d+)", value)
        if not control and not remind and not list_reminders and not cancel:
            return None
        when = now or utc_now()
        actor = str(actor_id)
        owner = self.owner_id is not None and actor == self.owner_id
        if control and not owner:
            raise PermissionError("only the verified owner can manage stream rules")
        mutating = bool(control and control["action"] in {"add", "edit", "enable", "disable", "remove", "welcome_on", "welcome_off"}) or bool(remind or cancel)
        if mutating:
            if not message_id:
                raise ValueError("message ID required for idempotent control")
            prior = self.db.execute("SELECT 1 FROM rr_automation_controls WHERE message_id=?", (str(message_id),)).fetchone()
            if prior:
                return None
        if remind:
            if remind[1]:
                ident = self.add_reminder(actor, stream_id, remind[1], remind[3], when)
            else:
                ident = self.add_reminder_at(actor, stream_id, _parse_when(remind[2]), remind[3], when)
            ack = "alarm #" + str(ident) + " queued"
        elif list_reminders:
            rows = self.list_reminders(actor, owner=owner)
            ack = "no pending alarms" if not rows else "alarms: " + "; ".join("#" + str(r[0]) + " " + r[3][11:16] + "Z " + r[2][:45] for r in rows[:5])
            ack = ack[:300]
        elif cancel:
            ack = "alarm cancelled" if self.cancel_reminder(cancel[1], actor, when, owner=owner) else "alarm not found"
        else:
            action = control["action"]
            if action in {"welcome_on", "welcome_off"}:
                if action == "welcome_off":
                    self.set_welcome(actor, enabled=False)
                    ack = "first-chat welcome paused"
                else:
                    self.set_welcome(actor, control["response"], enabled=True)
                    ack = "first-chat welcome saved"
            elif action in {"add", "edit"}:
                self.add_rule(actor, control["name"], control["phrase"], control["response"], whole_word=control.get("whole_word", True))
                ack = "rule " + control["name"] + " saved"
            elif action == "test":
                match = self.manage_rule(actor, "test", control["name"], sample_text=control.get("sample_text", ""))
                ack = "rule matches sample" if match else "rule does not match sample"
            elif action == "list":
                rows = self.manage_rule(actor, "list", None)
                ack = "no rules saved" if not rows else "rules: " + ", ".join(r[0] + (" (off)" if not r[4] else "") for r in rows[:12])
            else:
                self.manage_rule(actor, action, control["name"])
                ack = "rule " + control["name"] + " " + ("removed" if action == "remove" else action + "d")
        if mutating:
            with self.db:
                self.db.execute("INSERT OR IGNORE INTO rr_automation_controls(message_id,actor_id,ack,created_utc) VALUES(?,?,?,?)", (str(message_id), actor, ack, _iso(when)))
        return ack

    def purge_retained(self, now=None, retention_days=30):
        """Purge all automation event/dedup data and overdue reminders after 30d."""
        when = now or utc_now()
        cutoff = _iso(when - timedelta(days=max(1, min(30, retention_days))))
        iso_now = _iso(when)
        with self.db:
            # An undelivered reminder more than 30 days overdue is stale too.
            self.db.execute("DELETE FROM rr_reminders WHERE COALESCE(delivered_utc,cancelled_utc,due_utc)<? OR (delivered_utc IS NULL AND cancelled_utc IS NULL AND due_utc<?)", (cutoff, cutoff))
            self.db.execute("DELETE FROM rr_text_watches WHERE expires_utc<?", (cutoff,))
            self.db.execute("DELETE FROM rr_first_chat_seen WHERE seen_utc<?", (cutoff,))
            self.db.execute("DELETE FROM rr_processed_automation_messages WHERE created_utc<?", (cutoff,))
            self.db.execute("DELETE FROM rr_automation_controls WHERE created_utc<?", (cutoff,))
            self.db.execute("DELETE FROM rr_automation_rules WHERE expires_utc IS NOT NULL AND expires_utc<?", (iso_now,))
            self.db.execute("DELETE FROM rr_stream_promotions WHERE ended_utc IS NOT NULL AND ended_utc<?", (cutoff,))
            self.db.execute("UPDATE rr_rule_delivery SET last_utc=NULL WHERE singleton=1 AND last_utc<?", (cutoff,))

    def forget(self, user):
        with self.db:
            self.db.execute("DELETE FROM rr_reminders WHERE twitch_user_id=?", (user,))
            self.db.execute("DELETE FROM rr_text_watches WHERE twitch_user_id=?", (user,))
            self.db.execute("DELETE FROM rr_first_chat_seen WHERE twitch_user_id=?", (user,))


def parse_automation_control(text):
    """Parse a small owner-facing deterministic rule language.

    Returns a data-only operation dict or None. Authentication is deliberately left
    to the caller, which must compare the immutable Twitch ID before invoking it.
    """
    value = str(text).strip()
    match = re.fullmatch(r"(?i)whenever you hear (?:the word|the phrase) ['\"]?(.{1,80}?)['\"]?,? (?:say|reply) ['\"]?(.{1,180}?)['\"]?", value)
    if match:
        phrase, response = match.group(1).strip(" '\""), match.group(2).strip(" '\"")
        slug = re.sub(r"[^a-z0-9]+", "-", phrase.casefold()).strip("-")[:40] or "rule"
        return {"action": "add", "name": slug, "phrase": phrase, "response": response, "whole_word": True}
    match = re.fullmatch(r"(?i)when someone speaks for the first time in a stream, say ['\"]?(.{1,180}?)['\"]?", value)
    if match:
        return {"action": "welcome_on", "response": _public_text(match[1], 180)}
    if re.fullmatch(r"(?i)!rr\s+welcome\s+(?:off|disable)", value):
        return {"action": "welcome_off"}
    match = re.fullmatch(r"(?i)!rr\s+welcome\s+(?:set|on)\s+(.{1,180})", value)
    if match:
        return {"action": "welcome_on", "response": _public_text(match[1], 180)}
    match = re.fullmatch(r"(?i)!rr\s+rule\s+(add|edit)\s+([\w-]{1,40})\s+when\s+(.{1,80}?)\s*=>\s*(.{1,180})", value)
    if match:
        return {"action": "add", "name": match[2], "phrase": match[3].strip(), "response": match[4].strip(), "whole_word": True}
    match = re.fullmatch(r"(?i)!rr\s+rule\s+(list|remove|enable|disable)(?:\s+([\w-]{1,40}))?", value)
    if match:
        action, name = match.group(1).casefold(), match.group(2)
        if action != "list" and not name:
            return None
        return {"action": action, "name": name}
    match = re.fullmatch(r"(?i)!rr\s+rule\s+test\s+([\w-]{1,40})\s+(.{1,400})", value)
    if match:
        return {"action": "test", "name": match[1], "sample_text": match[2]}
    return None
