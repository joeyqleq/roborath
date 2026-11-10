"""Private, minimal public-chat activity counts with a 30-day retention limit.

No message text is stored here. Counts do not imply watch time, sentiment, or
personal traits. Public transcript retention is handled by its separate store.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import re

DEFAULT_RETENTION_DAYS = 30


def _utc(value=None):
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError("requires timezone-aware timestamp")
    return value.astimezone(timezone.utc)


def _day(value=None):
    return _utc(value).date().isoformat()


def _words(text):
    return len(re.findall(r"\b[\w’'-]+\b", str(text), flags=re.UNICODE))


def initialize(db):
    """Create v2 daily counts and migrate existing 5-minute aggregate data."""
    columns = {row[1] for row in db.execute("PRAGMA table_info(activity_buckets)")}
    if columns and "word_count" not in columns:
        # Preserve the old aggregates through a transactional roll-up. A stable
        # migration table lets a restart finish safely if the process is interrupted.
        db.execute("ALTER TABLE activity_buckets RENAME TO activity_buckets_legacy_v1")
    db.execute("""CREATE TABLE IF NOT EXISTS activity_buckets (
      twitch_user_id TEXT NOT NULL,
      twitch_login TEXT NOT NULL,
      stream_id TEXT NOT NULL,
      bucket_start_utc TEXT NOT NULL,
      message_count INTEGER NOT NULL DEFAULT 0,
      word_count INTEGER NOT NULL DEFAULT 0,
      reply_count INTEGER NOT NULL DEFAULT 0,
      native_reply_count INTEGER NOT NULL DEFAULT 0,
      bot_reply_count INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(twitch_user_id,stream_id,bucket_start_utc)
    )""")
    bucket_columns = {row[1] for row in db.execute("PRAGMA table_info(activity_buckets)")}
    if "native_reply_count" not in bucket_columns:
        db.execute("ALTER TABLE activity_buckets ADD COLUMN native_reply_count INTEGER NOT NULL DEFAULT 0")
    if "bot_reply_count" not in bucket_columns:
        db.execute("ALTER TABLE activity_buckets ADD COLUMN bot_reply_count INTEGER NOT NULL DEFAULT 0")
    db.execute("""CREATE TABLE IF NOT EXISTS activity_message_ids(
      message_id TEXT PRIMARY KEY, twitch_user_id TEXT NOT NULL,
      stream_id TEXT NOT NULL, bucket_start_utc TEXT NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS activity_reply_ids(
      message_id TEXT PRIMARY KEY, twitch_user_id TEXT NOT NULL,
      stream_id TEXT NOT NULL, bucket_start_utc TEXT NOT NULL
    )""")
    legacy_columns = {row[1] for row in db.execute("PRAGMA table_info(activity_buckets_legacy_v1)")}
    if legacy_columns:
        rows = db.execute("SELECT twitch_user_id,twitch_login,stream_id,bucket_start_utc,message_count FROM activity_buckets_legacy_v1").fetchall()
        for user_id, login, stream_id, timestamp, count in rows:
            try:
                when = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                day = when.astimezone(timezone.utc).date().isoformat()
            except ValueError:
                continue
            db.execute("""INSERT INTO activity_buckets
              (twitch_user_id,twitch_login,stream_id,bucket_start_utc,message_count)
              VALUES(?,?,?,?,?) ON CONFLICT(twitch_user_id,stream_id,bucket_start_utc)
              DO UPDATE SET message_count=message_count+excluded.message_count,
                twitch_login=excluded.twitch_login""", (user_id,login,stream_id,day,count))
        db.execute("DROP TABLE activity_buckets_legacy_v1")
    # The old index name followed the table during rename; recreate after dropping it.
    db.execute("CREATE INDEX IF NOT EXISTS activity_recent ON activity_buckets(bucket_start_utc,twitch_user_id)")
    db.commit()


def _upsert(db, user_id, login, stream_id, timestamp, *, messages=0, words=0, replies=0, native_replies=0, bot_replies=0):
    day = _day(timestamp)
    db.execute("""INSERT INTO activity_buckets
      (twitch_user_id,twitch_login,stream_id,bucket_start_utc,message_count,word_count,reply_count,native_reply_count,bot_reply_count)
      VALUES(?,?,?,?,?,?,?,?,?)
      ON CONFLICT(twitch_user_id,stream_id,bucket_start_utc)
      DO UPDATE SET message_count=message_count+excluded.message_count,
        word_count=word_count+excluded.word_count,
        reply_count=reply_count+excluded.reply_count,
        native_reply_count=native_reply_count+excluded.native_reply_count,
        bot_reply_count=bot_reply_count+excluded.bot_reply_count,
        twitch_login=excluded.twitch_login
    """, (str(user_id), str(login or "")[:25], str(stream_id), day, messages, words, replies, native_replies, bot_replies))
    return day


def record(db, user_id, login, stream_id, timestamp=None, message_id=None, text="", *, is_reply=False):
    """Count a public incoming message once; pass Twitch ID to guard replay.

    `is_reply` counts when this incoming message is itself a native Twitch reply
    authored by this user. It is optional when the adapter supplies reply tags.
    """
    if not user_id or not stream_id:
        return False
    when = _utc(timestamp)
    day = _day(when)
    with db:
        if message_id:
            cur = db.execute("INSERT OR IGNORE INTO activity_message_ids(message_id,twitch_user_id,stream_id,bucket_start_utc) VALUES(?,?,?,?)", (str(message_id), str(user_id), str(stream_id), day))
            if cur.rowcount != 1:
                return False
        native = int(bool(is_reply))
        _upsert(db, user_id, login, stream_id, when, messages=1, words=_words(text), replies=native, native_replies=native)
    return True


def record_reply(db, user_id, message_id, text="", timestamp=None, stream_id="", login=""):
    """Count an actual bot reply addressed to a viewer, once by Twitch message ID.

    Caller should invoke this only after the Twitch send succeeds, with the
    immutable recipient user ID. A local lack of server ACK means deployments may
    instead record successful socket sends and label them accordingly.
    """
    if not user_id or not message_id:
        return False
    when = _utc(timestamp)
    day = _day(when)
    with db:
        cur = db.execute("INSERT OR IGNORE INTO activity_reply_ids(message_id,twitch_user_id,stream_id,bucket_start_utc) VALUES(?,?,?,?)", (str(message_id), str(user_id), str(stream_id or "unknown"), day))
        if cur.rowcount != 1:
            return False
        _upsert(db, user_id, login, str(stream_id or "unknown"), when, replies=1, bot_replies=1)
    return True


def remove_user(db, user_id):
    with db:
        db.execute("DELETE FROM activity_buckets WHERE twitch_user_id=?", (str(user_id),))
        db.execute("DELETE FROM activity_message_ids WHERE twitch_user_id=?", (str(user_id),))
        db.execute("DELETE FROM activity_reply_ids WHERE twitch_user_id=?", (str(user_id),))


def prune(db, days=DEFAULT_RETENTION_DAYS, now=None):
    days = min(30, max(1, int(days)))
    cutoff = _day(_utc(now) - timedelta(days=days))
    with db:
        db.execute("DELETE FROM activity_buckets WHERE bucket_start_utc <= ?", (cutoff,))
        db.execute("DELETE FROM activity_message_ids WHERE bucket_start_utc <= ?", (cutoff,))
        db.execute("DELETE FROM activity_reply_ids WHERE bucket_start_utc <= ?", (cutoff,))


def regulars(db, since_days=30, minimum_active_buckets=3, minimum_days=3, now=None):
    """Return private aggregates; activity_buckets now counts active daily rows."""
    since_days = min(30, max(1, int(since_days)))
    reference = _utc(now)
    cutoff = (reference - timedelta(days=since_days)).date().isoformat()
    return db.execute("""SELECT twitch_user_id, MAX(twitch_login) AS latest_login,
       SUM(message_count) AS messages, COUNT(*) AS active_buckets,
       COUNT(DISTINCT stream_id) AS streams,
       COUNT(DISTINCT bucket_start_utc) AS active_days,
       SUM(word_count) AS words, SUM(reply_count) AS replies,
       SUM(native_reply_count) AS native_replies,
       SUM(bot_reply_count) AS bot_replies
       FROM activity_buckets WHERE bucket_start_utc >= ?
       GROUP BY twitch_user_id
       HAVING COUNT(*) >= ? AND COUNT(DISTINCT bucket_start_utc) >= ?
       ORDER BY active_buckets DESC,messages DESC LIMIT 100
    """, (cutoff, minimum_active_buckets, minimum_days)).fetchall()
