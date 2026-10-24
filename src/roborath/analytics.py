"""Private operator metrics from public chat activity; no psychological inference.

Never invoked from a public Twitch command. The source messages and notices are
subject to opt-out/deletion and a disclosed retention policy.
"""
from datetime import datetime, timezone, timedelta

BUCKET_SECONDS = 300
DEFAULT_RETENTION_DAYS = 180


def initialize(db):
    db.execute("""CREATE TABLE IF NOT EXISTS activity_buckets (
      twitch_user_id TEXT NOT NULL,
      twitch_login TEXT NOT NULL,
      stream_id TEXT NOT NULL,
      bucket_start_utc TEXT NOT NULL,
      message_count INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(twitch_user_id,stream_id,bucket_start_utc)
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS activity_recent
      ON activity_buckets(bucket_start_utc, twitch_user_id)""")
    db.commit()


def record(db, user_id, login, stream_id, timestamp=None):
    """Record a 5-min activity bucket; not a claim about viewing time."""
    if not user_id or not stream_id:
        return
    when = timestamp or datetime.now(timezone.utc)
    if when.tzinfo is None:
        raise ValueError("requires timezone-aware timestamp")
    epoch = int(when.timestamp()) // BUCKET_SECONDS * BUCKET_SECONDS
    bucket = datetime.fromtimestamp(epoch, timezone.utc).isoformat()
    db.execute("""INSERT INTO activity_buckets
      (twitch_user_id,twitch_login,stream_id,bucket_start_utc,message_count)
      VALUES(?,?,?,?,1)
      ON CONFLICT(twitch_user_id,stream_id,bucket_start_utc)
      DO UPDATE SET message_count=message_count+1,twitch_login=excluded.twitch_login
    """, (user_id, login, stream_id, bucket))


def remove_user(db, user_id):
    db.execute("DELETE FROM activity_buckets WHERE twitch_user_id=?", (user_id,))


def prune(db, days=DEFAULT_RETENTION_DAYS, now=None):
    reference = now or datetime.now(timezone.utc)
    cutoff = (reference - timedelta(days=days)).isoformat()
    db.execute("DELETE FROM activity_buckets WHERE bucket_start_utc < ?", (cutoff,))


def regulars(db, since_days=30, minimum_active_buckets=12, minimum_days=3, now=None):
    """Returns bounded aggregate engagement rankings for private operator UI only.

    An active bucket is a 5-minute interval with >=1 chat message; 12 buckets
    do not mean the viewer watched for 60 minutes.
    """
    reference = now or datetime.now(timezone.utc)
    cutoff = (reference - timedelta(days=since_days)).isoformat()
    return db.execute("""SELECT twitch_user_id, MAX(twitch_login) AS latest_login,
       SUM(message_count) AS messages, COUNT(*) AS active_buckets,
       COUNT(DISTINCT stream_id) AS streams,
       COUNT(DISTINCT SUBSTR(bucket_start_utc,1,10)) AS active_days
       FROM activity_buckets WHERE bucket_start_utc >= ?
       GROUP BY twitch_user_id
       HAVING COUNT(*) >= ? AND COUNT(DISTINCT SUBSTR(bucket_start_utc,1,10)) >= ?
       ORDER BY active_buckets DESC,messages DESC LIMIT 100
    """, (cutoff, minimum_active_buckets, minimum_days)).fetchall()
