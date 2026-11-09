"""Owner-controlled, persistent Twitch QA permissions and global silence.

Parsing is deliberately deterministic. The LLM never authorizes users.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
import sqlite3

CAPABILITIES = ("conversation", "fact", "research")
LOGIN = r'@?["\'“”‘’]?([a-z][a-z0-9_]{2,24})["\'“”‘’]?'
CAP = r'(all(?:\s+ai(?:\s+(?:abilities|capabilities|access))?)?|(?:general\s+)?conversation(?:al)?(?:\s+(?:abilities|access|ai))?|chat(?:ting)?|fact(?:[ -]?check(?:ing)?)?(?:\s+(?:abilities|access))?|research(?:\s+(?:abilities|access))?)'
PREFIX = re.compile(r'^(?:(?:hey\s+)?@?roborath\s*[,!:]?\s*|!rr\s+|!ask\s+)', re.I)
GRANT = re.compile(
    r'^(?:allow|give|grant|enable|authorize|let)\s+'
    r'(?:this\s+)?(?:user\s+)?'+LOGIN+
    r'(?:\s+(?:to(?:\s+(?:use|do|have|access))?|access\s+to|permission\s+to|the\s+ability\s+to|for))?\s+'
    +CAP+r'\s*[.!?]*$', re.I)
REVOKE = re.compile(
    r'^(?:remove|revoke|disable|deny|block|disallow)\s+'
    r'(?:this\s+)?(?:user\s+)?'+LOGIN+
    r'(?:\s+(?:from\s+(?:testing|using|accessing)|access\s+to|to|for))?\s*'
    +r'(?:'+CAP+r')?\s*[.!?]*$', re.I)
ACCESS = re.compile(r'^access\s+(grant|revoke)\s+'+LOGIN+r'\s+'+CAP+r'\s*$', re.I)
MUTE = {
    "stop talking", "stop replying", "stop responding", "don't reply to anyone",
    "do not reply to anyone", "dont reply to anyone", "don't respond to anyone",
    "stop talking to everyone", "go silent", "be quiet", "mute yourself",
    "silence", "mute", "shut up", "pause replies", "pause all replies",
    "stop talking don't reply to anyone", "stop talking do not reply to anyone",
}
RESUME = {
    "start talking", "resume talking", "start replying", "resume replying",
    "you can talk again", "you can reply again", "talk again", "unmute",
    "unmute yourself", "resume", "wake up", "resume all replies",
}
SHOW = {"show access", "list access", "who can use you", "who can talk to you",
        "list permitted users", "show permitted users", "access status",
        "show permissions", "list permissions"}

@dataclass(frozen=True)
class AdminIntent:
    action: str
    login: str = ""
    capability: str = ""

def normalized_cap(value: str) -> str:
    val=value.casefold().strip()
    if val.startswith("all"):return "all"
    if val.startswith(("fact",)):return "fact"
    if val.startswith("research"):return "research"
    return "conversation"

def parse_admin(raw: str) -> AdminIntent | None:
    text=raw.strip().replace("’","'").replace("‘","'").replace("“",'"').replace("”",'"')
    text=PREFIX.sub("",text,count=1).strip().casefold().rstrip(".!,")
    text=re.sub(r"[,;:]+\s*", " ",text).strip()
    if text in MUTE or re.fullmatch(
        r"(?:stop talking(?:\s+don't reply to anyone)?|don't reply to anyone|"
        r"do not reply to anyone|dont reply to anyone)"
        r"(?:\s+(?:until (?:i (?:say so|tell you(?: to resume| to start| otherwise)?)"
        r"|further notice)|for now))?",text):
        return AdminIntent("mute")
    if text in RESUME or text in ("start talking again","start responding again",
                                  "resume responding","you can reply now"):
        return AdminIntent("resume")
    if text in SHOW:return AdminIntent("show")
    for pattern in (ACCESS,GRANT,REVOKE):
        match=pattern.fullmatch(text)
        if not match:continue
        if pattern is ACCESS:
            action,login,cap=match.groups()
        else:
            login,cap=match.groups()
            action="grant" if pattern is GRANT else "revoke"
        if not cap:cap="all"
        return AdminIntent(action,login.lower(),normalized_cap(cap))
    return None

def requested_capability(raw: str) -> str | None:
    text=raw.strip().casefold()
    if parse_admin(text):return None
    if re.match(r'^(?:!ask\s|!rr\s+ask\s|!search\s|(?:hey\s+)?roborath\s*[:,!]\s|@roborath\s+ask\s)',text):
        return "conversation"
    if re.match(r'^(?:!fact|!check|!rr\s+(?:fact|check)|@roborath\s+(?:fact|check)|(?:hey\s+)?roborath\s*[:,!]\s*(?:fact|check))(?=\s|$)',text):
        return "fact"
    if re.match(r'^(?:!research|!rr\s+research|@roborath\s+research|(?:hey\s+)?roborath\s*[:,!]\s*research)(?=\s|$)',text):
        return "research"
    if re.fullmatch(r'!rr\s+help(?:\s+[12])?',text):return "help"
    if re.fullmatch(r'!(?:ask|search)\s*',text):return "conversation"
    if re.fullmatch(r'!(?:fact|check)\s*',text):return "fact"
    if re.fullmatch(r'!research\s*',text):return "research"
    return None

class TestAccess:
    def __init__(self,db:sqlite3.Connection,owner_id:str):
        self.db=db
        self.owner_id=str(owner_id or "")
        self.db.execute("""CREATE TABLE IF NOT EXISTS rr_test_access (
           user_id TEXT NOT NULL, login TEXT NOT NULL, capability TEXT NOT NULL,
           granted_at TEXT NOT NULL, PRIMARY KEY(user_id,capability))""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS rr_runtime_flags (
           key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS rr_admin_audit (
           message_id TEXT PRIMARY KEY, action TEXT NOT NULL, target_id TEXT,
           capability TEXT, at_utc TEXT NOT NULL)""")
        self.db.commit()

    def is_owner(self,user_id:str)->bool:
        return bool(self.owner_id and self.owner_id.isdigit() and user_id==self.owner_id)

    def muted(self)->bool:
        row=self.db.execute("SELECT value FROM rr_runtime_flags WHERE key='muted'").fetchone()
        return bool(row and row[0]=="1")

    def _audit(self,mid:str,action:str,target:str="",cap:str="")->bool:
        if not mid:return False
        cursor=self.db.execute(
            "INSERT OR IGNORE INTO rr_admin_audit VALUES (?,?,?,?,?)",
            (mid,action,target or None,cap or None,datetime.now(timezone.utc).isoformat()))
        return cursor.rowcount==1

    def set_mute(self,actor_id:str,mid:str,enabled:bool)->bool:
        if not self.is_owner(actor_id):raise PermissionError("only owner may mute or resume")
        with self.db:
            if not self._audit(mid,"mute" if enabled else "resume"):return False
            self.db.execute("""INSERT INTO rr_runtime_flags VALUES ('muted',?,?)
              ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
              ("1" if enabled else "0",datetime.now(timezone.utc).isoformat()))
        return True

    def change(self,actor_id:str,mid:str,target_id:str,login:str,cap:str,enabled:bool)->bool:
        if not self.is_owner(actor_id):raise PermissionError("only owner may administer")
        if not target_id.isdigit() or not target_id or target_id==self.owner_id:
            raise ValueError("invalid target Twitch ID")
        if cap not in (*CAPABILITIES,"all"):raise ValueError("invalid capability")
        if not re.fullmatch(r'[a-z][a-z0-9_]{2,24}',login):raise ValueError("invalid Twitch login")
        with self.db:
            if not self._audit(mid,"grant" if enabled else "revoke",target_id,cap):return False
            for capability in (CAPABILITIES if cap=="all" else (cap,)):
                if enabled:
                    self.db.execute("""INSERT INTO rr_test_access(user_id,login,capability,granted_at)
                       VALUES(?,?,?,?) ON CONFLICT(user_id,capability)
                       DO UPDATE SET login=excluded.login,granted_at=excluded.granted_at""",
                        (target_id,login,capability,datetime.now(timezone.utc).isoformat()))
                else:
                    self.db.execute("DELETE FROM rr_test_access WHERE user_id=? AND capability=?",
                                    (target_id,capability))
        return True

    def capabilities(self,user_id:str)->set[str]:
        if self.is_owner(user_id):return set(CAPABILITIES)
        return {row[0] for row in self.db.execute("SELECT capability FROM rr_test_access WHERE user_id=?",(user_id,))}

    def allowed(self,user_id:str,cap:str)->bool:
        if not self.owner_id or not self.owner_id.isdigit() or self.muted():return False
        if self.is_owner(user_id):return True
        if cap=="help":return bool(self.capabilities(user_id))
        return cap in self.capabilities(user_id)

    def can_receive(self,user_id:str,raw:str,strict:bool=True)->bool:
        if self.is_owner(user_id):return True
        if self.muted():return False
        if not strict:return True
        cap=requested_capability(raw)
        return bool(cap and self.allowed(user_id,cap))

    def summary(self)->str:
        rows=self.db.execute("""SELECT login,group_concat(capability,', ')
            FROM rr_test_access GROUP BY user_id ORDER BY login LIMIT 12""").fetchall()
        return ("muted. " if self.muted() else "listening. ")+(
            "; ".join(f"@{login}: {caps}" for login,caps in rows) if rows else "owner only")
