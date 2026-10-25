#!/usr/bin/env python3
"""Private read-only RoboRath operator console.

Run with filesystem permissions to access /var/lib/roborath/chat.sqlite3.
Never expose this script as a Twitch command or an unauthenticated HTTP API.
All queries are read-only and output bounded human-readable results.
"""
import argparse
import sqlite3
from pathlib import Path
from urllib.parse import quote


def connect_readonly(path: str) -> sqlite3.Connection:
    p = Path(path).expanduser().resolve(strict=True)
    if not p.is_file():
        raise ValueError("database path must be an existing regular file")
    uri = "file:" + quote(str(p), safe="/") + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=3)


def table_exists(db, name):
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def query(db, sql, params=()):
    try:
        return db.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        # Clear error for schemas not upgraded yet; do not leak SQL internals.
        return [("unavailable (schema not initialized)",)]


def status(db):
    for label, table in (
        ("received chat messages","chat_events"),
        ("tracked activity buckets","activity_buckets"),
        ("outstanding reminders","rr_reminders"),
        ("persistent supervisors","rr_supervisors"),
        ("mario kart winners","mario_winners"),
    ):
        if not table_exists(db, table):
            print(label + ": unavailable")
            continue
        where = " WHERE delivered_utc IS NULL" if table == "rr_reminders" else ""
        total = db.execute("SELECT COUNT(*) FROM " + table + where).fetchone()[0]
        print(label + ": " + str(total))


def regulars(db, limit):
    if not table_exists(db, "activity_buckets"):
        print("activity summaries not initialized")
        return
    rows = query(db, """SELECT twitch_login,COUNT(DISTINCT stream_id),
             COUNT(DISTINCT SUBSTR(bucket_start_utc,1,10)), SUM(message_count),
             COUNT(*) FROM activity_buckets GROUP BY twitch_user_id
             ORDER BY COUNT(*) DESC LIMIT ?""",(limit,))
    if not rows:
        print("no recorded chat activity")
    for login,streams,days,messages,buckets in rows:
        print(f"{login}: {messages} msgs, {buckets} active 5min buckets, {streams} streams, {days} days")


def quotas(db, limit):
    if not table_exists(db, "rr_consumptions"):
        print("quotas not initialized")
        return
    rows = query(db, """SELECT twitch_user_id,capability,scope,COUNT(*) AS used
           FROM rr_consumptions GROUP BY twitch_user_id,capability,scope
           ORDER BY MAX(used_utc) DESC LIMIT ?""",(limit,))
    if not rows: print("no quota usage recorded")
    for uid,capability,scope,used in rows:
        print(f"user {uid}: {capability} {used} used in {scope}")


def mario(db, limit):
    if not table_exists(db, "mario_winners"):
        print("mario kart mode not initialized")
        return
    rows=query(db, """SELECT player,COUNT(*) FROM mario_winners
        GROUP BY player ORDER BY COUNT(*) DESC,player LIMIT ?""",(limit,))
    if not rows: print("no winners yet")
    for name,wins in rows:print(f"{name}: {wins} first-place wins")


def main(argv=None):
    parser=argparse.ArgumentParser(description="RoboRath offline owner console")
    parser.add_argument("command",choices=("status","regulars","quotas","mario"))
    parser.add_argument("--db",default="/var/lib/roborath/chat.sqlite3")
    parser.add_argument("--limit",type=int,default=20)
    args=parser.parse_args(argv)
    if not 1<=args.limit<=100:parser.error("--limit must be 1..100")
    with connect_readonly(args.db) as db:
        {"status":status,"regulars":regulars,"quotas":quotas,
         "mario":mario}[args.command](db,*(() if args.command=="status" else (args.limit,)))


if __name__=="__main__":
    main()
