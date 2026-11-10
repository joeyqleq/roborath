"""Privacy-aware, stream-scoped archive of observed public Twitch chat.

The caller records every public PRIVMSG before bot eligibility checks. A stream
identifier must come from an authoritative stream lookup where available; a
synthetic connection/day identifier only proves observed connection coverage.
No private messages are accepted by this API.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

RETENTION_DAYS = 30
MAX_QUERY_CHARS = 256
MAX_RESULTS = 100
STOP_WORDS = frozenset("a an and are as at be before but by did do does for from had has have hey how i in is it me of on or say said that the their them there this to user was were what when where who why with about ago hour hours minute minutes stream chat summarize summarise discussion happened last".split())


def _utc(value: str | datetime | None, *, fallback: datetime | None = None) -> str:
    if value is None:
        dt = fallback or datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError("timestamp must be ISO-8601") from exc
    if dt.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


def initialize(db: sqlite3.Connection) -> None:
    """Create transcript tables and indexes in the existing private SQLite DB."""
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS transcript_sessions (
      stream_id TEXT PRIMARY KEY,
      first_observed_utc TEXT NOT NULL,
      last_observed_utc TEXT NOT NULL,
      message_count INTEGER NOT NULL DEFAULT 0,
      broadcaster_id TEXT,
      stream_started_utc TEXT,
      stream_ended_utc TEXT
    )""")
    columns = {row[1] for row in db.execute("PRAGMA table_info(transcript_sessions)")}
    for name, kind in (("broadcaster_id", "TEXT"), ("stream_started_utc", "TEXT"), ("stream_ended_utc", "TEXT")):
        if name not in columns:
            db.execute(f"ALTER TABLE transcript_sessions ADD COLUMN {name} {kind}")
    db.execute("""CREATE TABLE IF NOT EXISTS transcript_gaps (
      gap_id INTEGER PRIMARY KEY, stream_id TEXT NOT NULL,
      start_utc TEXT NOT NULL, end_utc TEXT,
      reason TEXT NOT NULL,
      FOREIGN KEY(stream_id) REFERENCES transcript_sessions(stream_id)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS transcript_optouts (
      twitch_user_id TEXT PRIMARY KEY,
      opted_out_utc TEXT NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS transcript_messages (
      stream_id TEXT NOT NULL,
      message_id TEXT NOT NULL,
      twitch_user_id TEXT NOT NULL,
      login TEXT NOT NULL,
      created_utc TEXT NOT NULL,
      received_utc TEXT NOT NULL,
      text TEXT NOT NULL,
      deleted_utc TEXT,
      PRIMARY KEY(message_id),
      FOREIGN KEY(stream_id) REFERENCES transcript_sessions(stream_id)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS transcript_time ON transcript_messages(stream_id,created_utc)")
    if 'reply_login' not in {r[1] for r in db.execute('PRAGMA table_info(transcript_messages)')}:
        db.execute("ALTER TABLE transcript_messages ADD COLUMN reply_login TEXT NOT NULL DEFAULT ''")
    db.execute("CREATE INDEX IF NOT EXISTS transcript_user_time ON transcript_messages(stream_id,twitch_user_id,created_utc)")
    db.execute("""CREATE TABLE IF NOT EXISTS transcript_summaries (
      summary_id INTEGER PRIMARY KEY,
      stream_id TEXT NOT NULL,
      window_start_utc TEXT NOT NULL,
      window_end_utc TEXT NOT NULL,
      summary TEXT NOT NULL,
      source_message_ids TEXT NOT NULL,
      generated_utc TEXT NOT NULL,
      FOREIGN KEY(stream_id) REFERENCES transcript_sessions(stream_id),
      UNIQUE(stream_id,window_start_utc,window_end_utc)
    )""")
    # External-content FTS complicates privacy deletion and migration. A regular
    # FTS table lets each deletion transaction explicitly remove its index row.
    try:
        db.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS transcript_fts USING fts5(
          message_id UNINDEXED, stream_id UNINDEXED, twitch_user_id UNINDEXED,
          login UNINDEXED, created_utc UNINDEXED, text,
          tokenize='unicode61 remove_diacritics 2'
        )""")
    except sqlite3.OperationalError as exc:
        raise RuntimeError("SQLite must be built with FTS5 for transcript search") from exc
    db.commit()


class TranscriptStore:
    """Public stream transcript with 30-day retention and user deletion controls."""

    def __init__(self, db: sqlite3.Connection, retention_days: int = RETENTION_DAYS):
        if retention_days < 1 or retention_days > RETENTION_DAYS:
            raise ValueError("retention_days must be between 1 and 30")
        self.db = db
        self.retention_days = retention_days
        initialize(db)
        self.purge()

    def record(self, stream_id: str, message_id: str, twitch_user_id: str,
               login: str, text: str, created_utc: str | datetime | None = None,
               received_utc: str | datetime | None = None, reply_login: str = '') -> bool:
        """Record an observed public message once. Returns False for opt-outs/dupes.

        `created_utc` should be Twitch's server timestamp when supplied. For IRC
        messages without one, receipt time is used and marked by the caller's
        connection-based stream ID; no prior/disconnected messages are inferred.
        """
        if not all((stream_id, message_id, twitch_user_id)):
            return False
        message = str(text or "")
        if not message:
            return False
        command = message.strip().lower()
        if command in {"!forgetme", "!optout", "!stop"}:
            self.opt_out(str(twitch_user_id), now=received_utc)
            return False
        if command == "!optin":
            self.opt_in(str(twitch_user_id))
            return False
        received = _utc(received_utc)
        created = _utc(created_utc, fallback=datetime.fromisoformat(received))
        if self.db.execute("SELECT 1 FROM transcript_optouts WHERE twitch_user_id=?",
                           (str(twitch_user_id),)).fetchone():
            return False
        try:
            with self.db:
                self.db.execute("""INSERT OR IGNORE INTO transcript_sessions
                  (stream_id,first_observed_utc,last_observed_utc,message_count)
                  VALUES(?,?,?,0)""", (stream_id, created, created))
                result = self.db.execute("""INSERT OR IGNORE INTO transcript_messages
                  (stream_id,message_id,twitch_user_id,login,created_utc,received_utc,text,reply_login)
                  VALUES(?,?,?,?,?,?,?,?)""",
                  (stream_id, str(message_id), str(twitch_user_id), str(login).lower(),
                   created, received, message,str(reply_login)))
                if result.rowcount != 1:
                    return False
                self.db.execute("""INSERT INTO transcript_fts
                  (message_id,stream_id,twitch_user_id,login,created_utc,text)
                  VALUES(?,?,?,?,?,?)""",
                  (str(message_id), stream_id, str(twitch_user_id), str(login).lower(), created, message))
                self.db.execute("""UPDATE transcript_sessions SET
                  first_observed_utc=CASE WHEN message_count=0 THEN ? ELSE MIN(first_observed_utc,?) END,
                  last_observed_utc=MAX(last_observed_utc,?),
                  message_count=message_count+1 WHERE stream_id=?""",
                  (created, created, created, stream_id))
        except sqlite3.IntegrityError:
            return False
        return True

    def observe_stream(self, stream_id: str, broadcaster_id: str | None = None,
                       started_utc: str | datetime | None = None) -> None:
        """Attach verified broadcaster/start metadata from Twitch Helix/EventSub."""
        if not stream_id:
            raise ValueError("stream_id is required")
        started = _utc(started_utc) if started_utc is not None else None
        with self.db:
            self.db.execute("""INSERT INTO transcript_sessions
              (stream_id,first_observed_utc,last_observed_utc,message_count,broadcaster_id,stream_started_utc)
              VALUES(?,?,?,0,?,?) ON CONFLICT(stream_id) DO UPDATE SET
              broadcaster_id=COALESCE(excluded.broadcaster_id,transcript_sessions.broadcaster_id),
              stream_started_utc=COALESCE(excluded.stream_started_utc,transcript_sessions.stream_started_utc)""",
              (str(stream_id), started or _utc(None), started or _utc(None),
               str(broadcaster_id) if broadcaster_id else None, started))

    def mark_gap(self, stream_id: str, start_utc: str | datetime,
                 end_utc: str | datetime | None, reason: str = "connection_lost") -> None:
        """Record a known capture interruption; open gaps may be closed later."""
        start = _utc(start_utc)
        end = _utc(end_utc) if end_utc is not None else None
        if end is not None and end < start:
            raise ValueError("gap end precedes start")
        with self.db:
            self.db.execute("""INSERT INTO transcript_gaps(stream_id,start_utc,end_utc,reason)
              VALUES(?,?,?,?)""", (str(stream_id), start, end, str(reason)[:100]))

    def close_gap(self, stream_id: str, end_utc: str | datetime) -> None:
        end = _utc(end_utc)
        with self.db:
            self.db.execute("""UPDATE transcript_gaps SET end_utc=?
              WHERE gap_id=(SELECT gap_id FROM transcript_gaps WHERE stream_id=? AND end_utc IS NULL
              ORDER BY start_utc DESC LIMIT 1)""", (end, str(stream_id)))

    def delete_message(self, message_id: str) -> int:
        """Propagate a Twitch deletion to transcript, FTS and derived summaries."""
        rows = self.db.execute("SELECT stream_id,twitch_user_id,created_utc FROM transcript_messages WHERE message_id=? AND deleted_utc IS NULL",
                               (str(message_id),)).fetchall()
        if not rows:
            return 0
        with self.db:
            for stream, user, when in rows:
                self.db.execute("DELETE FROM transcript_fts WHERE message_id=? AND stream_id=?",
                                (str(message_id), stream))
                self.db.execute("DELETE FROM transcript_messages WHERE message_id=? AND stream_id=?",
                                (str(message_id), stream))
                self.db.execute("DELETE FROM transcript_summaries WHERE stream_id=? AND window_start_utc<=? AND window_end_utc>=?",
                                (stream, when, when))
            self._refresh_sessions({row[0] for row in rows})
        return len(rows)

    def delete_user(self, twitch_user_id: str) -> set[str]:
        """Erase one user's messages and dependent summaries, without opting out.

        Returns affected stream IDs so the caller can redact any derived answer
        rows in its own tables. Use this for Twitch moderation deletion.
        """
        user = str(twitch_user_id)
        streams = {row[0] for row in self.db.execute(
            "SELECT DISTINCT stream_id FROM transcript_messages WHERE twitch_user_id=?", (user,))}
        with self.db:
            self.db.execute("DELETE FROM transcript_fts WHERE twitch_user_id=?", (user,))
            self.db.execute("DELETE FROM transcript_messages WHERE twitch_user_id=?", (user,))
            for stream in streams:
                self.db.execute("DELETE FROM transcript_summaries WHERE stream_id=?", (stream,))
            self._refresh_sessions(streams)
        return streams

    def delete_stream(self, stream_id: str) -> int:
        """Purge all captured text and derived summaries for one stream."""
        sid = str(stream_id)
        count = self.db.execute("SELECT COUNT(*) FROM transcript_messages WHERE stream_id=?", (sid,)).fetchone()[0]
        with self.db:
            self.db.execute("DELETE FROM transcript_fts WHERE stream_id=?", (sid,))
            self.db.execute("DELETE FROM transcript_messages WHERE stream_id=?", (sid,))
            self.db.execute("DELETE FROM transcript_summaries WHERE stream_id=?", (sid,))
            self.db.execute("DELETE FROM transcript_gaps WHERE stream_id=?", (sid,))
            self.db.execute("DELETE FROM transcript_sessions WHERE stream_id=?", (sid,))
        return count

    def opt_out(self, twitch_user_id: str, now: str | datetime | None = None) -> int:
        """Persist opt-out and erase this user's messages and dependent summaries."""
        user = str(twitch_user_id)
        rows = self.db.execute("SELECT stream_id,created_utc FROM transcript_messages WHERE twitch_user_id=?",
                               (user,)).fetchall()
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO transcript_optouts VALUES(?,?)", (user, _utc(now)))
            self.db.execute("DELETE FROM transcript_fts WHERE twitch_user_id=?", (user,))
            self.db.execute("DELETE FROM transcript_messages WHERE twitch_user_id=?", (user,))
            for stream, when in rows:
                self.db.execute("DELETE FROM transcript_summaries WHERE stream_id=? AND window_start_utc<=? AND window_end_utc>=?",
                                (stream, when, when))
            self._refresh_sessions({row[0] for row in rows})
        return len(rows)

    def opt_in(self, twitch_user_id: str) -> None:
        """Allow new archive entries; previously deleted messages stay deleted."""
        with self.db:
            self.db.execute("DELETE FROM transcript_optouts WHERE twitch_user_id=?", (str(twitch_user_id),))

    def is_opted_out(self, twitch_user_id: str) -> bool:
        return bool(self.db.execute("SELECT 1 FROM transcript_optouts WHERE twitch_user_id=?",
                                    (str(twitch_user_id),)).fetchone())

    def purge(self, now: str | datetime | None = None) -> int:
        """Delete expired messages, FTS rows, summaries and empty session records."""
        cutoff = _utc(now, fallback=datetime.now(timezone.utc))
        cutoff = (datetime.fromisoformat(cutoff) - timedelta(days=self.retention_days)).isoformat(timespec="microseconds")
        expired = self.db.execute("SELECT stream_id,message_id FROM transcript_messages WHERE created_utc<?",
                                  (cutoff,)).fetchall()
        streams = {row[0] for row in expired}
        with self.db:
            self.db.execute("DELETE FROM transcript_fts WHERE created_utc<?", (cutoff,))
            self.db.execute("DELETE FROM transcript_messages WHERE created_utc<?", (cutoff,))
            # Expire a summary if any of its supporting message window is old.
            self.db.execute("DELETE FROM transcript_summaries WHERE window_start_utc<?", (cutoff,))
            self.db.execute("DELETE FROM transcript_gaps WHERE end_utc IS NOT NULL AND end_utc<?", (cutoff,))
            self._refresh_sessions(streams)
        return len(expired)

    def search(self, stream_id: str, query: str, twitch_user_id: str | None = None,
               login: str | None = None,
               start_utc: str | datetime | None = None, end_utc: str | datetime | None = None,
               limit: int = 20) -> list[dict[str, Any]]:
        """Search within one stream; FTS query terms are safely quoted/ANDed."""
        query = str(query or "")[:MAX_QUERY_CHARS]
        terms = [term for term in re.findall(r"[\w'-]+", query, flags=re.UNICODE)
                 if term.lower() not in STOP_WORDS and len(term) > 1][:8]
        if not terms:
            return []
        match = " AND ".join('"' + term.replace('"', '""') + '"' for term in terms)
        clauses = ["f.stream_id=?", "transcript_fts MATCH ?"]
        params: list[Any] = [str(stream_id), match]
        if twitch_user_id is not None:
            clauses.append("f.twitch_user_id=?")
            params.append(str(twitch_user_id))
        if login is not None:
            clauses.append("f.login=?")
            params.append(str(login).lower().lstrip("@"))
        if start_utc is not None:
            clauses.append("f.created_utc>=?")
            params.append(_utc(start_utc))
        if end_utc is not None:
            clauses.append("f.created_utc<=?")
            params.append(_utc(end_utc))
        params.append(min(max(1, int(limit)), MAX_RESULTS))
        rows = self.db.execute("""SELECT m.message_id,m.twitch_user_id,m.login,m.created_utc,m.text
          FROM transcript_fts f JOIN transcript_messages m
            ON m.stream_id=f.stream_id AND m.message_id=f.message_id
          WHERE """ + " AND ".join(clauses) + " ORDER BY f.created_utc LIMIT ?", params).fetchall()
        return [dict(message_id=r[0], twitch_user_id=r[1], login=r[2], created_utc=r[3], text=r[4]) for r in rows]

    def query_context(self, stream_id: str, query: str,
                      now: str | datetime | None = None, limit: int = 12) -> list[dict[str, Any]]:
        """Resolve common memory questions to bounded, attributed literal excerpts."""
        question = str(query or "")[:MAX_QUERY_CHARS]
        reference = datetime.fromisoformat(_utc(now))
        within = re.search(r"\b(\d{1,2})\s*(hour|hr|minute|min)s?\s+ago\b", question, re.I)
        start = end = None
        if within:
            amount = int(within.group(1))
            delta = timedelta(hours=amount) if within.group(2).lower().startswith(("hour", "hr")) else timedelta(minutes=amount)
            end, start = reference - delta + timedelta(minutes=15), reference - delta - timedelta(minutes=15)
        login = None
        named = re.search(r"\b(?:user|viewer|from)\s+@?([a-zA-Z0-9_]{3,25})\b|@([a-zA-Z0-9_]{3,25})", question, re.I)
        if named:
            candidate = (named.group(1) or named.group(2)).lower()
            if candidate not in STOP_WORDS:
                login = candidate
        correction_query = bool(re.search(r"\b(correct(?:ed|ion)?|disagree(?:d)?|wrong|false|not true)\b", question, re.I))
        if correction_query:
            rows = self.db.execute("""SELECT message_id,twitch_user_id,login,created_utc,text
              FROM transcript_messages WHERE stream_id=? AND created_utc>=?
              AND (lower(text) LIKE '%actually%' OR lower(text) LIKE '%correction%' OR
                   lower(text) LIKE '%wrong%' OR lower(text) LIKE '%not true%' OR
                   lower(text) LIKE '%that''s false%' OR lower(text) LIKE '%incorrect%')
              ORDER BY created_utc LIMIT ?""",
              (str(stream_id), _utc(reference - timedelta(hours=5)), min(max(1, limit), MAX_RESULTS))).fetchall()
            return [dict(message_id=r[0], twitch_user_id=r[1], login=r[2], created_utc=r[3], text=r[4]) for r in rows]
        topic = re.sub(r"\b(?:who|what|when|where|why|did|does|do|say|said|mention(?:ed)?|first|before|after|the|a|an|anyone|someone|user|viewer|from|ago|\d{1,2}|hours?|hrs?|minutes?|mins?)\b", " ", question, flags=re.I)
        if login:
            topic = re.sub(r"(?i)\b@?" + re.escape(login) + r"\b", " ", topic)
        topic = " ".join(topic.split())
        terms = [word for word in re.findall(r"[\w'-]+", topic) if word.lower() not in STOP_WORDS and len(word) > 1]
        hits = self.search(stream_id, " ".join(terms), login=login,
                           start_utc=start, end_utc=end, limit=limit) if terms else []
        if not terms and (login or start):
            clauses=["stream_id=?"]
            args=[str(stream_id)]
            if login:clauses.append("login=?");args.append(login)
            if start:clauses.append("created_utc>=?");args.append(_utc(start))
            if end:clauses.append("created_utc<=?");args.append(_utc(end))
            args.append(min(max(1,limit),MAX_RESULTS))
            rows=self.db.execute("SELECT message_id,twitch_user_id,login,created_utc,text FROM transcript_messages WHERE "+" AND ".join(clauses)+" ORDER BY created_utc LIMIT ?",args).fetchall()
            hits=[dict(message_id=r[0],twitch_user_id=r[1],login=r[2],created_utc=r[3],text=r[4]) for r in rows]
        qlow = question.lower()
        if hits and re.search(r"\b(before|earlier|preced(?:e|ed))\b", qlow):
            first = min(hits, key=lambda row: row["created_utc"])
            prior = self.db.execute("""SELECT message_id,twitch_user_id,login,created_utc,text
              FROM transcript_messages WHERE stream_id=? AND created_utc<?
              ORDER BY created_utc DESC LIMIT ?""",
              (str(stream_id), first["created_utc"], min(max(1, limit), MAX_RESULTS))).fetchall()
            hits = [dict(message_id=r[0], twitch_user_id=r[1], login=r[2], created_utc=r[3], text=r[4]) for r in reversed(prior)]
        elif hits and re.search(r"\b(first|earliest)\b", qlow):
            hits = [min(hits, key=lambda row: row["created_utc"])]
        return hits

    def answer_question(self, stream_id: str, question: str,
                        now: str | datetime | None = None, limit: int = 5) -> dict[str, Any]:
        """Format sourced transcript excerpts without inventing event conclusions."""
        results = self.query_context(stream_id, question, now=now, limit=limit)
        coverage = self.coverage(stream_id)
        return {"found": bool(results), "stream_id": str(stream_id),
                "coverage": coverage, "excerpts": results[:min(max(1, limit), 12)],
                "note": ("These are public chat excerpts, not verified factual claims. "
                         "Coverage gaps may mean earlier messages were not captured.")}

    def chunked_excerpts(self, stream_id: str, start_utc: str | datetime,
                         end_utc: str | datetime, chunk_minutes: int = 30,
                         max_excerpts: int = 8) -> list[dict[str, Any]]:
        """Build deterministic, source-linked timeline chunks with literal excerpts."""
        start, end = datetime.fromisoformat(_utc(start_utc)), datetime.fromisoformat(_utc(end_utc))
        if end < start or not 1 <= chunk_minutes <= 120:
            raise ValueError("invalid chunk interval")
        rows = self.db.execute("""SELECT message_id,twitch_user_id,login,created_utc,text
          FROM transcript_messages WHERE stream_id=? AND created_utc>=? AND created_utc<=?
          ORDER BY created_utc""", (str(stream_id), start.isoformat(), end.isoformat())).fetchall()
        grouped: dict[datetime, list[dict[str, Any]]] = {}
        for row in rows:
            created = datetime.fromisoformat(row[3])
            offset = int((created - start).total_seconds() // (chunk_minutes * 60))
            chunk_start = start + timedelta(minutes=offset * chunk_minutes)
            grouped.setdefault(chunk_start, []).append(dict(message_id=row[0], twitch_user_id=row[1],
                login=row[2], created_utc=row[3], text=row[4]))
        chunks = []
        for chunk_start, messages in sorted(grouped.items()):
            chosen = messages[:max(1, min(max_excerpts, 20))]
            chunks.append({"window_start_utc": _utc(chunk_start),
                "window_end_utc": _utc(min(chunk_start + timedelta(minutes=chunk_minutes), end)),
                "summary": "Observed excerpts: " + " | ".join(
                    f"@{m['login']}: {m['text'][:240]}" for m in chosen),
                "source_message_ids": [m["message_id"] for m in chosen],
                "message_count": len(messages), "sampled": len(chosen) < len(messages)})
        return chunks

    def recent_context(self, stream_id: str, since_utc: str | datetime | None = None,
                       limit: int = 100) -> list[dict[str, Any]]:
        """Return shared whole-stream messages, never another stream's content."""
        since = _utc(since_utc, fallback=datetime.now(timezone.utc)-timedelta(hours=5))
        rows = self.db.execute("""SELECT message_id,twitch_user_id,login,created_utc,text
          FROM transcript_messages WHERE stream_id=? AND created_utc>=?
          ORDER BY created_utc DESC LIMIT ?""",
          (str(stream_id), since, min(max(1, int(limit)), MAX_RESULTS))).fetchall()
        rows.reverse()
        return [dict(message_id=r[0], twitch_user_id=r[1], login=r[2], created_utc=r[3], text=r[4]) for r in rows]

    def store_summary(self, stream_id: str, window_start_utc: str | datetime,
                      window_end_utc: str | datetime, summary: str,
                      source_message_ids: list[str], generated_utc: str | datetime | None = None) -> bool:
        """Store a bounded summary only when every citation belongs to its window."""
        start, end = _utc(window_start_utc), _utc(window_end_utc)
        if start > end or not summary.strip() or len(summary) > 4000:
            return False
        ids = list(dict.fromkeys(str(x) for x in source_message_ids))[:100]
        if not ids:
            return False
        placeholders = ",".join("?" for _ in ids)
        valid = self.db.execute(f"""SELECT COUNT(*) FROM transcript_messages
          WHERE stream_id=? AND message_id IN ({placeholders}) AND created_utc>=? AND created_utc<=?""",
          [str(stream_id), *ids, start, end]).fetchone()[0]
        if valid != len(ids):
            return False
        with self.db:
            self.db.execute("""INSERT INTO transcript_summaries
              (stream_id,window_start_utc,window_end_utc,summary,source_message_ids,generated_utc)
              VALUES(?,?,?,?,?,?) ON CONFLICT(stream_id,window_start_utc,window_end_utc)
              DO UPDATE SET summary=excluded.summary,source_message_ids=excluded.source_message_ids,
              generated_utc=excluded.generated_utc""",
              (str(stream_id), start, end, summary.strip(), json.dumps(ids), _utc(generated_utc)))
        return True

    def summaries(self, stream_id: str, start_utc: str | datetime | None = None,
                  end_utc: str | datetime | None = None, limit: int = 20) -> list[dict[str, Any]]:
        clauses, params = ["stream_id=?"], [str(stream_id)]
        if start_utc is not None:
            clauses.append("window_end_utc>=?"); params.append(_utc(start_utc))
        if end_utc is not None:
            clauses.append("window_start_utc<=?"); params.append(_utc(end_utc))
        params.append(min(max(1, int(limit)), 100))
        rows = self.db.execute("SELECT window_start_utc,window_end_utc,summary,source_message_ids,generated_utc FROM transcript_summaries WHERE " + " AND ".join(clauses) + " ORDER BY window_start_utc LIMIT ?", params).fetchall()
        return [dict(window_start_utc=r[0], window_end_utc=r[1], summary=r[2], source_message_ids=json.loads(r[3]), generated_utc=r[4]) for r in rows]

    def maintenance(self, now: str | datetime | None = None) -> dict[str, int]:
        """Daily operator-scheduled retention pass; constructor also purges on startup."""
        expired = self.purge(now=now)
        self.db.execute("PRAGMA optimize")
        return {"expired_messages": expired}

    def export_jsonl(self, stream_id: str, start_utc: str | datetime | None = None,
                     end_utc: str | datetime | None = None,
                     operator_authorized: bool = False, limit: int = 1000) -> str:
        """Return a bounded export only when the caller confirms operator auth."""
        if not operator_authorized:
            raise PermissionError("operator authorization required")
        clauses, params = ["stream_id=?"], [str(stream_id)]
        if start_utc is not None:
            clauses.append("created_utc>=?"); params.append(_utc(start_utc))
        if end_utc is not None:
            clauses.append("created_utc<=?"); params.append(_utc(end_utc))
        params.append(min(max(1, int(limit)), 1000))
        rows = self.db.execute("SELECT message_id,twitch_user_id,login,created_utc,text FROM transcript_messages WHERE " +
            " AND ".join(clauses) + " ORDER BY created_utc LIMIT ?", params).fetchall()
        return "".join(json.dumps(dict(message_id=r[0], twitch_user_id=r[1], login=r[2],
            created_utc=r[3], text=r[4]), ensure_ascii=False) + "\n" for r in rows)

    def export_text(self, stream_id: str, start_utc: str | datetime | None = None,
                    end_utc: str | datetime | None = None,
                    operator_authorized: bool = False, limit: int = 1000) -> str:
        """Render bounded public chat as `username: text`; timestamps stay in SQLite."""
        if not operator_authorized:
            raise PermissionError("operator authorization required")
        clauses, params = ["stream_id=?"], [str(stream_id)]
        if start_utc is not None:
            clauses.append("created_utc>=?"); params.append(_utc(start_utc))
        if end_utc is not None:
            clauses.append("created_utc<=?"); params.append(_utc(end_utc))
        params.append(min(max(1, int(limit)), 1000))
        rows = self.db.execute("SELECT login,text FROM transcript_messages WHERE " +
            " AND ".join(clauses) + " ORDER BY created_utc LIMIT ?", params).fetchall()
        return "".join(f"{login}: {text.replace(chr(13), ' ').replace(chr(10), ' ')}\n" for login, text in rows)

    def coverage(self, stream_id: str) -> dict[str, Any]:
        """Report only observed interval; full-broadcast coverage is never assumed."""
        row = self.db.execute("SELECT first_observed_utc,last_observed_utc,message_count,broadcaster_id,stream_started_utc FROM transcript_sessions WHERE stream_id=?",
                              (str(stream_id),)).fetchone()
        if row is None:
            return {"stream_id": str(stream_id), "observed": False, "complete": False,
                    "message_count": 0, "first_observed_utc": None, "last_observed_utc": None,
                    "coverage_note": "No public messages observed for this stream identifier."}
        return {"stream_id": str(stream_id), "observed": bool(row[2]), "complete": None,
                "message_count": row[2], "first_observed_utc": row[0] if row[2] else None, "last_observed_utc": row[1] if row[2] else None,
                "broadcaster_id": row[3], "stream_started_utc": row[4],
                "gaps": [dict(start_utc=x[0], end_utc=x[1], reason=x[2]) for x in self.db.execute(
                    "SELECT start_utc,end_utc,reason FROM transcript_gaps WHERE stream_id=? ORDER BY start_utc", (str(stream_id),))],
                "coverage_note": "Only messages received while connected are archived; full-stream coverage is unknown."}

    def activity_question(self,stream_id,question,now=None):
        """Exact retained-chat statistics, never viewer join/watch-time inference."""
        value=str(question).strip()
        if not re.search(r'\b(?:how many (?:words|characters|chars|messages|replies)|what time|when did|how long|first message|first spoke)\b',value,re.I):return None
        named=re.search(r'\b(?:user|viewer)\s+@?([a-z0-9_]{3,25})\b|@([a-z0-9_]{3,25})\b',value,re.I)
        if not named:
            named=re.search(r'\b(?:did|has)\s+@?([a-z0-9_]{3,25})\s+(?:say|send|write|speak|been|come|join|start|first)',value,re.I)
        if not named:return None
        login=next(x for x in named.groups() if x).lower()
        identity=self.db.execute('SELECT twitch_user_id FROM transcript_messages WHERE stream_id=? AND login=? ORDER BY created_utc DESC LIMIT 1',(stream_id,login)).fetchone()
        if not identity:return '@'+login+': no retained messages captured in this stream. Joining/watching time is not recorded.'
        uid=identity[0]
        rows=self.db.execute('SELECT created_utc,text,login,reply_login FROM transcript_messages WHERE stream_id=? AND twitch_user_id=? ORDER BY created_utc',(stream_id,uid)).fetchall()
        first=datetime.fromisoformat(rows[0][0]);reference=datetime.fromisoformat(_utc(now))
        minutes=max(0,int((reference-first).total_seconds()/60))
        from text_metrics import content_counts
        counts=[content_counts(r[1],r[2],r[3]) for r in rows]
        words=sum(r[0] for r in counts);chars=sum(r[1] for r in counts)
        stamp=first.strftime('%H:%M UTC')
        text=f'@{login}: {len(rows)} captured messages, {words} words, {chars} characters (no spaces/usernames); first spoke {stamp}, {minutes//60}h {minutes%60}m ago. '
        if re.search(r'\b(?:come|join|entered)\b',value,re.I):text+='First captured speech, not join time. '
        text+='Retained chat only; missed/deleted messages excluded.'
        return text

    def _refresh_sessions(self, stream_ids: set[str]) -> None:
        for stream in stream_ids:
            stats = self.db.execute("SELECT MIN(created_utc),MAX(created_utc),COUNT(*) FROM transcript_messages WHERE stream_id=?",
                                    (stream,)).fetchone()
            if stats[2]:
                self.db.execute("UPDATE transcript_sessions SET first_observed_utc=?,last_observed_utc=?,message_count=? WHERE stream_id=?",
                                (*stats, stream))
            else:
                metadata = self.db.execute("SELECT broadcaster_id,stream_started_utc,stream_ended_utc FROM transcript_sessions WHERE stream_id=?", (stream,)).fetchone()
                self.db.execute("DELETE FROM transcript_summaries WHERE stream_id=?", (stream,))
                if not metadata or not any(metadata):
                    self.db.execute("DELETE FROM transcript_gaps WHERE stream_id=?", (stream,))
                    self.db.execute("DELETE FROM transcript_sessions WHERE stream_id=?", (stream,))
