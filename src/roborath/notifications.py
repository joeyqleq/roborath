"""Bounded text-trigger and reminder queue; no arbitrary code execution.

Only public Twitch text received by the bridge is inspected. No message scans
Twitch video, private chat, audio, user devices, or historical data.
"""
import re
import sqlite3
from datetime import datetime, timezone, timedelta

def utc_now():
    return datetime.now(timezone.utc)

def parse_duration(text):
    match=re.fullmatch(r"(\d{1,4})(m|h|d)",str(text).lower())
    if not match:return None
    n=int(match.group(1))
    seconds=n*{"m":60,"h":3600,"d":86400}[match.group(2)]
    return seconds if 60<=seconds<=7*86400 else None

class Notifications:
    def __init__(self,db:sqlite3.Connection):
        self.db=db
        self.db.execute("""CREATE TABLE IF NOT EXISTS rr_reminders(
           id INTEGER PRIMARY KEY AUTOINCREMENT, twitch_user_id TEXT NOT NULL,
           stream_id TEXT NOT NULL, message TEXT NOT NULL,
           due_utc TEXT NOT NULL, delivered_utc TEXT
        )""")
        self.db.execute("""CREATE INDEX IF NOT EXISTS rr_reminders_due
           ON rr_reminders(due_utc,delivered_utc)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS rr_text_watches(
           id INTEGER PRIMARY KEY AUTOINCREMENT, twitch_user_id TEXT NOT NULL,
           stream_id TEXT NOT NULL, phrase TEXT NOT NULL,
           response TEXT NOT NULL, expires_utc TEXT NOT NULL,
           fired_utc TEXT, enabled INTEGER NOT NULL DEFAULT 1
        )""")
        self.db.commit()

    def add_reminder(self,user,stream,delay,text,now=None):
        seconds=parse_duration(delay)
        if seconds is None:raise ValueError("use 1m-7d, eg 20m or 2h")
        message=str(text).strip()[:240]
        if not message:raise ValueError("reminder text required")
        when=now or utc_now()
        pending=self.db.execute("""SELECT COUNT(*) FROM rr_reminders
            WHERE twitch_user_id=? AND delivered_utc IS NULL""",(user,)).fetchone()[0]
        if pending>=5:raise ValueError("5 outstanding reminders max")
        with self.db:
            cur=self.db.execute("""INSERT INTO rr_reminders
              (twitch_user_id,stream_id,message,due_utc)
              VALUES(?,?,?,?)""",
              (user,stream,message,(when+timedelta(seconds=seconds)).isoformat()))
            return cur.lastrowid

    def due(self,now=None,limit=5):
        when=(now or utc_now()).isoformat()
        return self.db.execute("""SELECT id,twitch_user_id,message FROM rr_reminders
           WHERE delivered_utc IS NULL AND due_utc<=?
           ORDER BY due_utc ASC LIMIT ?""",(when,min(limit,10))).fetchall()

    def delivered(self,id,now=None):
        with self.db:
            self.db.execute("""UPDATE rr_reminders SET delivered_utc=?
                WHERE id=? AND delivered_utc IS NULL""",
                ((now or utc_now()).isoformat(),id))

    def watch(self,user,stream,phrase,response,now=None):
        phrase=str(phrase).strip().lower()[:80]
        response=str(response).strip()[:180]
        if len(phrase)<3 or not response:
            raise ValueError("watch phrase and response required")
        active=self.db.execute("""SELECT COUNT(*) FROM rr_text_watches
          WHERE twitch_user_id=? AND enabled=1 AND expires_utc>?""",
          (user,(now or utc_now()).isoformat())).fetchone()[0]
        if active>=3:raise ValueError("3 active watches max")
        expires=(now or utc_now())+timedelta(hours=12)
        with self.db:
            cur=self.db.execute("""INSERT INTO rr_text_watches
              (twitch_user_id,stream_id,phrase,response,expires_utc)
              VALUES(?,?,?,?,?)""",(user,stream,phrase,response,expires.isoformat()))
        return cur.lastrowid

    def scan(self,stream,text,now=None,limit=1):
        """Return max one alert; 5min cooldown per watch, same stream only."""
        when=now or utc_now()
        rows=self.db.execute("""SELECT id,twitch_user_id,phrase,response,fired_utc
             FROM rr_text_watches WHERE stream_id=? AND enabled=1 AND expires_utc>?
             ORDER BY id LIMIT 100""",(stream,when.isoformat())).fetchall()
        fired=[]
        for ident,user,phrase,response,last in rows:
            if phrase not in str(text).casefold():continue
            if last and datetime.fromisoformat(last)>when-timedelta(minutes=5):
                continue
            fired.append((ident,user,response))
            if len(fired)>=limit:break
        for ident,user,response in fired:
            with self.db:
                self.db.execute("UPDATE rr_text_watches SET fired_utc=? WHERE id=?",
                                (when.isoformat(),ident))
        return fired

    def forget(self,user):
        with self.db:
            self.db.execute("DELETE FROM rr_reminders WHERE twitch_user_id=?",(user,))
            self.db.execute("DELETE FROM rr_text_watches WHERE twitch_user_id=?",(user,))
