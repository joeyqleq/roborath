"""Local operator-only read-only transcript/analytics export.

Access is controlled by the private database's filesystem permissions. This is
not a public HTTP or Twitch endpoint. Run with the authorized service account.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sqlite3


def render(db,kind,stream_id=None):
    cutoff=(datetime.now(timezone.utc)-timedelta(days=30)).isoformat()
    if kind=="transcript":
        if not stream_id:raise ValueError("transcript requires --stream")
        rows=db.execute("""SELECT login,text FROM transcript_messages
            WHERE stream_id=? AND created_utc>=?
            AND twitch_user_id NOT IN (SELECT twitch_user_id FROM transcript_optouts)
            ORDER BY created_utc,message_id""",(stream_id,cutoff))
        return "\n".join(login+": "+re.sub(r"\s+"," ",text).strip() for login,text in rows)
    if kind=="streams":
        rows=db.execute("""SELECT stream_id,MIN(created_utc),MAX(created_utc),COUNT(*)
            FROM transcript_messages WHERE created_utc>=? GROUP BY stream_id
            ORDER BY MAX(created_utc) DESC""",(cutoff,))
        return json.dumps([dict(zip(("stream_id","first_received","last_received","messages"),r)) for r in rows],indent=2)
    where="bucket_start_utc>?"
    args=[cutoff[:10]]
    if stream_id:where+=" AND stream_id=?";args.append(stream_id)
    rows=db.execute("""SELECT twitch_user_id,MAX(twitch_login),SUM(message_count),
        SUM(word_count),SUM(native_reply_count),SUM(bot_reply_count),SUM(character_count) FROM activity_buckets WHERE """+where+
        " GROUP BY twitch_user_id ORDER BY SUM(message_count) DESC",args)
    return json.dumps([dict(zip(("user_id","username","messages","words","native_replies_sent","bot_replies_received","characters"),r)) for r in rows],indent=2)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind",choices=("streams","transcript","analytics"))
    parser.add_argument("--db",required=True,help="private SQLite database path")
    parser.add_argument("--stream",help="exact stream ID")
    args=parser.parse_args()
    uri=Path(args.db).resolve().as_uri()+"?mode=ro"
    db=sqlite3.connect(uri,uri=True)
    try:print(render(db,args.kind,args.stream))
    finally:db.close()


if __name__=="__main__":main()
