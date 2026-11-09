"""Mario Kart community mode: explicit roster and first-place-only results.

A round requires two independent matching chat reports or a verified operator.
No inference is made from ordinary, unrelated chat messages.
"""
import re
import sqlite3
from difflib import get_close_matches
from datetime import datetime, timezone, timedelta

def alias(s):
    return re.sub(r"[^a-z0-9_]", "", str(s).lower())

class Mario:
    def __init__(self, db: sqlite3.Connection):
        self.db=db
        self.db.execute("""CREATE TABLE IF NOT EXISTS mario_sessions (
          stream_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
          current_round INTEGER NOT NULL DEFAULT 1)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS mario_players (
          stream_id TEXT NOT NULL, player TEXT NOT NULL,
          PRIMARY KEY(stream_id,player))""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS mario_votes (
          stream_id TEXT NOT NULL, round_no INTEGER NOT NULL,
          reporter_id TEXT NOT NULL, player TEXT NOT NULL,
          PRIMARY KEY(stream_id,round_no,reporter_id))""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS mario_winners (
          stream_id TEXT NOT NULL, round_no INTEGER NOT NULL,
          player TEXT NOT NULL, confirmed_utc TEXT NOT NULL,
          PRIMARY KEY(stream_id,round_no))""")
        # Compatible migration for sessions created before the expiration feature.
        cols={row[1] for row in self.db.execute("PRAGMA table_info(mario_sessions)")}
        if "enabled_utc" not in cols:
            self.db.execute("ALTER TABLE mario_sessions ADD COLUMN enabled_utc TEXT")
        self.db.commit()

    MAX_HOURS = 5

    def active(self, stream):
        row=self.db.execute("SELECT enabled,enabled_utc FROM mario_sessions WHERE stream_id=?",
                            (stream,)).fetchone()
        if not row or not row[0]:
            return False
        try:
            started=datetime.fromisoformat(row[1])
            if started.tzinfo is None:
                started=started.replace(tzinfo=timezone.utc)
            valid=datetime.now(timezone.utc)-started < timedelta(hours=self.MAX_HOURS)
        except (TypeError, ValueError):
            valid=False
        if not valid:
            self.enable(stream,False)
        return valid

    def enable(self, stream, enabled=True):
        timestamp=datetime.now(timezone.utc).isoformat() if enabled else None
        with self.db:
            self.db.execute("""INSERT INTO mario_sessions(stream_id,enabled,enabled_utc)
               VALUES(?,?,?) ON CONFLICT(stream_id) DO UPDATE SET enabled=excluded.enabled,
               enabled_utc=excluded.enabled_utc""", (stream,int(enabled),timestamp))

    def reset(self,stream):
        """Clear this stream's mode, roster, votes, winners, and round counter."""
        with self.db:
            for table in ("mario_votes","mario_winners","mario_players"):
                self.db.execute("DELETE FROM "+table+" WHERE stream_id=?",(stream,))
            self.db.execute("""INSERT INTO mario_sessions(stream_id,enabled,current_round,enabled_utc)
                VALUES(?,0,1,NULL)
                ON CONFLICT(stream_id) DO UPDATE SET enabled=0,current_round=1,enabled_utc=NULL""",
                (stream,))
        return "mario kart reset: mode off, round 1, roster and scores cleared"

    def status(self,stream):
        return ("on" if self.active(stream) else "off"),self.current_round(stream) or 1,len(self.players(stream))

    def roster(self, stream, names):
        cleaned=[alias(n) for n in names]
        if not 2 <= len(cleaned) <= 12 or any(len(x)<2 for x in cleaned) or len(cleaned)!=len(set(cleaned)):
            raise ValueError("roster needs 2-12 distinct player nicknames")
        with self.db:
            self.db.execute("DELETE FROM mario_players WHERE stream_id=?",(stream,))
            self.db.executemany("INSERT INTO mario_players VALUES (?,?)",[(stream,n) for n in cleaned])

    def players(self,stream):
        return [r[0] for r in self.db.execute(
            "SELECT player FROM mario_players WHERE stream_id=? ORDER BY player",(stream,))]

    def resolve(self,stream,typed):
        players=self.players(stream)
        name=alias(typed)
        if name in players:return name
        guesses=get_close_matches(name,players,n=2,cutoff=0.77)
        # Conservative typo matching: no ambiguity allowed.
        if len(guesses)==1 and len(name)>=3:return guesses[0]
        return None

    def current_round(self,stream):
        x=self.db.execute("SELECT current_round FROM mario_sessions WHERE stream_id=?",(stream,)).fetchone()
        return x[0] if x else None

    def vote(self,stream, reporter_id, typed, operator=False):
        if not self.active(stream):return "mario kart mode is off"
        player=self.resolve(stream,typed)
        if not player:return "player not in roster. ask a supervisor to update it"
        round_no=self.current_round(stream)
        existing=self.db.execute("SELECT player FROM mario_winners WHERE stream_id=? AND round_no=?",
                                  (stream,round_no)).fetchone()
        if existing:return "round "+str(round_no)+" already recorded: "+existing[0]+". use !rr mario next"
        if not reporter_id:return "missing twitch user id"
        with self.db:
            prior=self.db.execute("""SELECT player FROM mario_votes
               WHERE stream_id=? AND round_no=? AND reporter_id=?""",
               (stream,round_no,reporter_id)).fetchone()
            if prior and not operator:return "vote already recorded for this round"
            self.db.execute("""INSERT OR REPLACE INTO mario_votes
             (stream_id,round_no,reporter_id,player) VALUES (?,?,?,?)""",
             (stream,round_no,reporter_id,player))
            votes=self.db.execute("""SELECT COUNT(DISTINCT reporter_id)
              FROM mario_votes WHERE stream_id=? AND round_no=? AND player=?""",
              (stream,round_no,player)).fetchone()[0]
            if operator or votes>=2:
                self.db.execute("""INSERT INTO mario_winners
                  (stream_id,round_no,player,confirmed_utc) VALUES(?,?,?,?)""",
                  (stream,round_no,player,datetime.now(timezone.utc).isoformat()))
                return "round "+str(round_no)+" first place: "+player+" ✓"
            return "vote noted: "+player+" for round "+str(round_no)+"; 1 more independent report needed"

    def next_round(self,stream):
        if not self.active(stream):return "mario kart mode is off"
        round_no=self.current_round(stream)
        confirmed=self.db.execute("SELECT 1 FROM mario_winners WHERE stream_id=? AND round_no=?",
                                  (stream,round_no)).fetchone()
        if not confirmed:return "confirm the current round's first-place winner first"
        with self.db:
            self.db.execute("UPDATE mario_sessions SET current_round=current_round+1 WHERE stream_id=?",(stream,))
        return "mario kart round "+str(round_no+1)+" is open. use !rr win <player>"

    def scores(self,stream=None):
        if stream:
            return self.db.execute("""SELECT player, COUNT(*) FROM mario_winners
              WHERE stream_id=? GROUP BY player ORDER BY COUNT(*) DESC,player""",(stream,)).fetchall()
        return self.db.execute("""SELECT player, COUNT(*) FROM mario_winners
          GROUP BY player ORDER BY COUNT(*) DESC,player""").fetchall()
