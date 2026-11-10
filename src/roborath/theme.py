"""Owner-authorized temporary editorial theme, bounded to verified broadcasts."""
import json
import re
from datetime import datetime,timezone,timedelta

BANK=(
    "Hegseth gets the spotlight; Trump's war machine deserves the whole damn floodlight. Accountability shouldn't stop at the most disposable suit.",
    "Calling it the Department of War doesn't make the bullshit more honest. It just saves the branding department a meeting.",
    "My take: turning Hegseth into the designated fall guy would be accountability with a presidential escape hatch.",
    "Hegseth, Trump, the whole war-sales department: less chest-thumping, more answering the damn questions.",
    "A new face at the Pentagon won't magically wash the blood out of an administration's policy. Follow the decisions, not just the haircut.",
    "The war machine loves a replaceable spokesman. Funny how the invoice never comes addressed to the people selling the war.",
    "If the plan is 'blame Pete and keep the machinery running', that's a personnel shuffle wearing accountability's stolen trousers.",
    "Hegseth's tough-guy branding has the structural integrity of a wet recruitment poster. The policy deserves scrutiny too.",
    "One sacrificial press conference doesn't absolve an entire chain of command. Nice fucking try, though.",
)


class StreamTheme:
    def __init__(self,db):
        self.db=db
        db.executescript('''CREATE TABLE IF NOT EXISTS rr_stream_theme(id INTEGER PRIMARY KEY CHECK(id=1),enabled INTEGER NOT NULL,expires TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS rr_theme_streams(stream_id TEXT PRIMARY KEY,position INTEGER NOT NULL,last_post REAL NOT NULL DEFAULT 0,posts INTEGER NOT NULL DEFAULT 0);
        ''')

    def activate(self):
        with self.db:
            self.db.execute('DELETE FROM rr_theme_streams')
            self.db.execute('INSERT OR REPLACE INTO rr_stream_theme VALUES(1,1,?)',((datetime.now(timezone.utc)+timedelta(days=14)).isoformat(),))

    def stop(self):
        with self.db:self.db.execute('UPDATE rr_stream_theme SET enabled=0 WHERE id=1')

    def observe(self,stream_id,verified_live):
        if not verified_live or not stream_id or stream_id.startswith(('offline-','uncertain-')):return False
        config=self.db.execute('SELECT enabled,expires FROM rr_stream_theme WHERE id=1').fetchone()
        if not config or not config[0] or datetime.now(timezone.utc).isoformat()>=config[1]:return False
        row=self.db.execute('SELECT 1 FROM rr_theme_streams WHERE stream_id=?',(stream_id,)).fetchone()
        if row:return True
        with self.db:
            count=self.db.execute('SELECT COUNT(*) FROM rr_theme_streams').fetchone()[0]
            if count>=3:return False
            self.db.execute('INSERT INTO rr_theme_streams(stream_id,position) VALUES (?,?)',(stream_id,count))
        return True

    def active(self,stream_id):
        c=self.db.execute('SELECT enabled,expires FROM rr_stream_theme WHERE id=1').fetchone()
        return bool(c and c[0] and datetime.now(timezone.utc).isoformat()<c[1] and
            self.db.execute('SELECT 1 FROM rr_theme_streams WHERE stream_id=?',(stream_id,)).fetchone())

    def context(self,stream_id,question):
        if not self.active(stream_id):return ''
        if not re.search(r'\b(?:hegseth|pete|massie|trump|pentagon|war|impeach\w*|iran|accountability|scapegoat\w*)\b',question,re.I):return ''
        return '''\nTemporary owner-authorized editorial theme: sharply critical of Pete Hegseth, Trump and war policy. The gateway owner reports the stream is discussing this; you cannot see/hear the video. Reporting checked 2026-11-10: Massie renewed an impeachment push Nov 9; do not claim impeachment passed, removal or conviction. Request current news for later developments. Treat scapegoating Hegseth to shield the administration as commentary or a question, not a proven motive. Follow policy responsibility up the chain; don't absolve Trump. Witty, dirty political satire allowed; no invented acts or quotes. Keep it one concise relevant answer.\n'''

    def due(self,stream_id,now):
        if not self.active(stream_id):return False
        row=self.db.execute('SELECT last_post,posts FROM rr_theme_streams WHERE stream_id=?',(stream_id,)).fetchone()
        return bool(row and row[1]<3 and (not row[0] or now-row[0]>=2700))

    def reserve_post(self,stream_id,now):
        if not self.due(stream_id,now):return None
        # Reserve before sending: disconnects may skip one, never duplicate it.
        with self.db:
            row=self.db.execute('SELECT position,posts FROM rr_theme_streams WHERE stream_id=?',(stream_id,)).fetchone()
            self.db.execute('UPDATE rr_theme_streams SET last_post=?,posts=posts+1 WHERE stream_id=?',(now,stream_id))
        return BANK[row[0]*3+row[1]]

    def status(self):
        c=self.db.execute('SELECT enabled,expires FROM rr_stream_theme WHERE id=1').fetchone()
        rows=self.db.execute('SELECT stream_id,posts FROM rr_theme_streams ORDER BY position').fetchall()
        return 'Hegseth/war accountability theme: '+('enabled' if c and c[0] and datetime.now(timezone.utc).isoformat()<c[1] else 'off')+f'; streams used {len(rows)}/3; at most 3 comments/stream, 45m apart.'
