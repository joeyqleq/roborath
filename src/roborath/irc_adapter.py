#!/usr/bin/env python3
"""Unprivileged Twitch IRC chat-client transport for Dr. Greenthumb.

Uses a user OAuth token with only chat:read + chat:edit granted via a trusted
registered client. No Twitch developer application or channel moderator role
is needed. The IRC adapter reuses Bridge's routing, per-viewer memory, consent,
cooldowns, and Mattermost integration.
"""
import asyncio
import contextlib
import json
import logging
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from websockets.asyncio.client import connect
from bridge import Bridge, clean_request
from access_control import requested_capability
from twitch_auth import access_token
from formatting import validate_final_output, utf8_clip
from analytics import record_reply as analytics_record_reply, remove_user as analytics_remove_user
from policy import OWNER_TWITCH_ID

LOG = logging.getLogger("gt-twitch-irc")
IRC_WS = "wss://irc-ws.chat.twitch.tv:443"
NICK = os.getenv("TWITCH_IRC_NICK", "").strip().lower()
CHANNEL = os.getenv("TWITCH_CHANNEL_LOGIN", "").strip().lower().lstrip("#")
TOKEN = os.getenv("TWITCH_IRC_TOKEN", "").strip().removeprefix("oauth:")
CLIENT_ID = os.getenv("TWITCH_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "").strip()
TOKEN_FILE = os.getenv("TWITCH_TOKEN_FILE", "").strip()
MIN_REPLY_INTERVAL = max(2, int(os.getenv("GT_GLOBAL_REPLY_COOLDOWN_SECONDS", "12")))
THREADED_REPLIES = os.getenv("ROBORATH_THREADED_REPLIES", "false").lower() == "true"
OWNER_ONLY_TEST = os.getenv("ROBORATH_OWNER_ONLY_TEST_MODE", "false").lower() == "true"
OWNER_ID = os.getenv("ROBORATH_OWNER_TWITCH_USER_ID", "")


def parse_tags(source):
    """Decode IRCv3 tags, without logging raw authenticated frames."""
    result = {}
    for part in source.split(";"):
        key, _, value = part.partition("=")
        if not key:
            continue
        result[key] = (value.replace(r"\s", " ").replace(r"\:", ";")
                       .replace(r"\r", "\r").replace(r"\n", "\n")
                       .replace(chr(92) + chr(92), chr(92)))
    return result


def parse_privmsg(line):
    """Normalize a Twitch IRC PRIVMSG into Bridge's EventSub message format."""
    tags = {}
    if line.startswith("@"):
        raw, sep, line = line[1:].partition(" ")
        if not sep:
            return None
        tags = parse_tags(raw)
    match = re.match(r"^:([^! ]+)![^ ]+ PRIVMSG #([A-Za-z0-9_]+) :(.*)$", line)
    if not match:
        return None
    login, channel, body = match.groups()
    mid = tags.get("id", "")
    uid = tags.get("user-id", "")
    if not mid or not uid.isdigit():
        return None
    created=None
    stamp=tags.get("tmi-sent-ts","")
    if stamp.isdigit():
        try:created=datetime.fromtimestamp(int(stamp)/1000,timezone.utc).isoformat()
        except (ValueError,OverflowError,OSError):pass
    return channel.lower(), {
        "message_id": mid,
        "chatter_user_id": uid,
        "chatter_user_login": login.lower(),
        "message": {"text": body},
        "room_id": tags.get("room-id", ""),
        "created_utc": created,
        "reply_parent_user_id": tags.get("reply-parent-user-id", ""),
        "reply_parent_user_login": tags.get("reply-parent-user-login", ""),
    }


def sanitize_public_reply(answer: str, login: str = "") -> str:
    """Strip model hype, duplicate speaker mentions, and decorative clutter."""
    answer=re.sub(r"\s+", " ", validate_final_output(answer)).strip()
    # Twitch's IRC chat is a public one-line plain-text surface.
    answer=re.sub(r"(?<!\S)#[A-Za-z][A-Za-z0-9_]*\b", "", answer)
    answer=re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]", "", answer)
    answer="".join(ch for ch in answer if unicodedata.category(ch) not in ("Cc","Cf") or ch==" ")
    if re.fullmatch(r"[a-z0-9_]{3,25}",login or "",re.I):
        identity=re.escape(login)
        # Avoid '@joeyleq Hey @joeyleq', even when the model puts the
        # second mention after a greeting instead of at the start.
        answer=re.sub(r"(?i)(?<!\w)@"+identity+r"\b", "", answer)
        answer=re.sub(r"(?i)^(?:hey|hi|hello|yo)\b[!, ]*\s*(?:—|[-,:])?\s*(?=\w)", "", answer)
    answer=re.sub(r"(?i)\s*(?:[.!?]\s*)?(?:what(?:'s| is) on your mind|how can i help(?: you)?|ask away)[?!\s]*$", "", answer)
    answer=re.sub(r"\s+", " ", answer).strip(" ,:;—-")
    return answer


class IRCAdapter:
    def __init__(self):
        self.bridge = Bridge()
        self.ws = None
        self.token = TOKEN
        self.send_lock = asyncio.Lock()
        self.last_send = 0.0
        self.room_id = ""
        self.stream_cache = ("", 0.0)
        self.token_checked_until = 0.0
        self._unknown_session="uncertain-"+uuid4().hex
        self._stream_lock=asyncio.Lock()
        self._chat_tasks=set()
        self._disconnect_at=None
        self.bridge.twitch_reply = self.reply
        self.bridge.stream_id = self.stream_id
        self.bridge.lookup_twitch_login = self.lookup_login

    async def validate_token(self):
        if TOKEN_FILE:
            if not CLIENT_ID or not CLIENT_SECRET:
                raise PermissionError("missing confidential Twitch OAuth app config")
            self.token, bot_id = await access_token(CLIENT_ID, CLIENT_SECRET,
                                                     TOKEN_FILE, required_login=NICK)
            LOG.info("OAuth valid for RoboRath user ID %s", bot_id)
        if not self.token:
            raise PermissionError("RoboRath has no authorized OAuth token")
        async with httpx.AsyncClient(timeout=12) as http:
            response = await http.get("https://id.twitch.tv/oauth2/validate",
                                      headers={"Authorization": "OAuth " + self.token})
            response.raise_for_status()
            record = response.json()
            scopes = set(record.get("scopes", []))
            if not {"chat:read", "chat:edit"} <= scopes:
                raise ValueError("IRC token must include chat:read and chat:edit")
            if record.get("login", "").lower() != NICK:
                raise ValueError("Token account does not match TWITCH_IRC_NICK")
            if CLIENT_ID and record.get("client_id") != CLIENT_ID:
                raise ValueError("Token client_id does not match configured client_id")
            LOG.info("Twitch token valid for account %s", NICK)
            return record.get("client_id", "")

    async def stream_id(self):
        async with self._stream_lock:
            return await self._refresh_stream()

    async def _refresh_stream(self):
        if time.monotonic() < self.stream_cache[1]:
            return self.stream_cache[0]
        # IRC may remain connected for hours after its initial OAuth refresh.
        # The independent Helix request must use a CURRENT bearer token.
        if TOKEN_FILE and time.monotonic() >= self.token_checked_until:
            try:
                self.token, _ = await access_token(CLIENT_ID, CLIENT_SECRET,
                                                   TOKEN_FILE, required_login=NICK)
                self.token_checked_until = time.monotonic() + 300
            except (httpx.HTTPError, PermissionError, ValueError, KeyError) as exc:
                LOG.warning("Stream auth refresh unavailable (%s)",type(exc).__name__)
        if self.room_id and CLIENT_ID:
            try:
                async with httpx.AsyncClient(timeout=8) as http:
                    r = await http.get("https://api.twitch.tv/helix/streams",
                        params={"user_id": self.room_id},
                        headers={"Client-ID": CLIENT_ID,
                                 "Authorization": "Bearer " + self.token})
                    r.raise_for_status()
                    streams = r.json().get("data", [])
                    if streams:
                        details=streams[0]
                        identity = str(details["id"])
                        started=details.get("started_at")
                        self.bridge.live_stream={"id":identity,"started_at":started}
                        self.bridge.live_verified_until=time.monotonic()+60
                        self.bridge.theme.observe(identity,True)
                        self.bridge.transcript.observe_stream(identity,self.room_id,started)
                        if started:
                            self.bridge.notifications.start_stream(identity,datetime.fromisoformat(started.replace("Z","+00:00")))
                        self.stream_cache = (identity, time.monotonic() + 60)
                        return identity
                    if self.bridge.live_stream:
                        self.bridge.notifications.end_stream(self.bridge.live_stream["id"])
                    self.bridge.live_stream=None
                    self.bridge.live_verified_until=0.0
                    identity="offline-"+CHANNEL+"-"+datetime.now(timezone.utc).strftime("%Y%m%d")
                    self.stream_cache=(identity,time.monotonic()+60)
                    return identity
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                LOG.warning("Stream lookup unavailable (%s)", type(exc).__name__)
        # Fallback per-channel UTC day; not guaranteed to distinguish 2 streams
        # on the same day. Use Helix stream lookup when client ID is supplied.
        # API uncertainty must not merge multiple real broadcasts into a day.
        self.bridge.live_verified_until=0.0
        self.bridge.live_stream=None
        identity = self._unknown_session
        self.stream_cache = (identity, time.monotonic() + 15)
        return identity

    async def lookup_login(self,login:str)->tuple[str,str]:
        """Resolve public Twitch login via Helix, returning immutable user ID.

        Reject unknown or mismatched names. Never use chat-supplied display
        names or numeric user IDs as authorization evidence.
        """
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,24}",login or ""):
            raise ValueError("invalid Twitch login")
        if not CLIENT_ID or not self.token:
            raise PermissionError("no authenticated Twitch API session")
        # A refreshed service OAuth token works for public /users lookup.
        if TOKEN_FILE and time.monotonic()>=self.token_checked_until:
            self.token,_=await access_token(CLIENT_ID,CLIENT_SECRET,TOKEN_FILE,
                                            required_login=NICK)
            self.token_checked_until=time.monotonic()+240
        async with httpx.AsyncClient(timeout=9,follow_redirects=False) as http:
            response=await http.get("https://api.twitch.tv/helix/users",
                params={"login":login},headers={
                    "Client-ID":CLIENT_ID,"Authorization":"Bearer "+self.token})
            response.raise_for_status()
        records=response.json().get("data",[])
        matches=[x for x in records if x.get("login","").casefold()==login.casefold()
                 and str(x.get("id","")).isdigit()]
        if len(matches)!=1:raise LookupError("Twitch login not resolved uniquely")
        return str(matches[0]["id"]),matches[0]["login"].lower()

    async def reply(self, answer, message_id):
        if not self.ws:
            raise ConnectionError("IRC socket not connected")
        self.bridge.authorize_reply(message_id)
        # Plain channel replies avoid Twitch's visually confusing mini-thread.
        # Prefix the verified sender's login instead of making the model guess.
        login=""
        recipient=None
        if message_id:
            row = self.bridge.db.execute(
                "SELECT twitch_login,twitch_user_id,stream_id FROM chat_events WHERE message_id=?",
                (message_id,)).fetchone()
            login = row[0] if row else self.bridge._privacy_replies.get(message_id,("",""))[1]
            recipient=row
        answer=sanitize_public_reply(answer,login)
        if recipient and recipient[1]==OWNER_TWITCH_ID and not re.search(r"\b(?:Chairman|Boss|Captain|Leader|Comandante)\b",answer,re.I):
            answer="Boss, "+answer
        if not THREADED_REPLIES and re.fullmatch(r"[a-z0-9_]{3,25}",login or "",re.I):
            answer="@"+login+" "+answer
        answer=utf8_clip(answer,420)
        if not answer:
            return
        async with self.send_lock:
            remaining = MIN_REPLY_INTERVAL - (time.monotonic() - self.last_send)
            if remaining > 0:
                await asyncio.sleep(remaining)
            # Check again after pacing: a mute/revoke may have arrived while a
            # previous model call was generating or the IRC queue was waiting.
            self.bridge.authorize_reply(message_id)
            reference = message_id if re.fullmatch(r"[A-Za-z0-9-]{1,90}", message_id) else ""
            tag = "@reply-parent-msg-id=" + reference + " " if reference and THREADED_REPLIES else ""
            await self.ws.send(tag + "PRIVMSG #" + CHANNEL + " :" + answer + "\r\n")
            self.last_send = time.monotonic()
            import hashlib
            reply_key=(message_id or "scheduled")+":"+hashlib.sha256(answer.encode()).hexdigest()[:16]
            if recipient and not self.bridge.transcript.is_opted_out(recipient[1]):
                # IRC exposes socket-send success, not a Twitch server message ACK.
                # Distinct research parts count separately; repeated same parts dedup.
                analytics_record_reply(self.bridge.db,recipient[1],reply_key,
                    stream_id=recipient[2],login=recipient[0])
            if not recipient or not self.bridge.transcript.is_opted_out(recipient[1]):
                stream=recipient[2] if recipient else (self.bridge.live_stream or {}).get('id')
                if stream:
                    self.bridge.transcript.record(stream,"sent:"+reply_key,
                        '1591621882',NICK or 'roborath',answer)
            if message_id:
                # A successful websocket send is NOT a Twitch server ACK, but
                # it proves a control command wasn't silently ignored.
                self.bridge.db.execute(
                    """UPDATE chat_events SET answer_text=?,status='answered',
                       command=COALESCE(command,'control')
                       WHERE message_id=? AND status='observed'""",(answer,message_id))
                self.bridge.db.commit()

    async def reminder_loop(self):
        """Post due reminders while connected, with the same paced IRC queue."""
        while self.ws:
            try:
                self.bridge.prune()
                stream=await self.stream_id()
                strict=os.getenv("ROBORATH_OWNER_ONLY_TEST_MODE","false").lower()=="true"
                live=bool(self.bridge.live_stream and time.monotonic()<self.bridge.live_verified_until)
                # This scoped campaign has explicit owner authorization for
                # public remarks; ordinary QA-gated timers remain separate.
                if live and not self.bridge.access.muted() and self.bridge.access.invokes.access('theme-public') is not False:
                    themed=self.bridge.theme.reserve_post(stream,time.time())
                    if themed:
                        key='theme:'+stream
                        self.bridge._theme_posts.add(key)
                        try:await self.reply(themed,key)
                        finally:self.bridge._theme_posts.discard(key)
                promotion=self.bridge.notifications.follow_tick(stream,live=live,
                    muted=self.bridge.access.muted(),owner_only=strict)
                if promotion:
                    await self.reply(promotion,"")
                if strict or not live or self.bridge.access.muted():
                    await asyncio.sleep(10)
                    continue
                due = self.bridge.notifications.due(limit=4)
                for reminder_id, user_id, note in due:
                    row=self.bridge.db.execute("""SELECT twitch_login FROM chat_events
                        WHERE twitch_user_id=? ORDER BY created_utc DESC LIMIT 1""",
                        (user_id,)).fetchone()
                    if not row or self.bridge.transcript.is_opted_out(user_id):
                        # Retain the reminder; user identity can be resolved later.
                        continue
                    await self.reply("@"+row[0]+" reminder: "+note,"")
                    self.bridge.notifications.delivered(reminder_id)
            except Exception as err:
                LOG.warning("reminder delivery deferred (%s)",type(err).__name__)
            await asyncio.sleep(10)

    async def run(self):
        while True:
            try:
                await self.validate_token()
                async with connect(IRC_WS, ping_interval=40, ping_timeout=30,
                                   max_size=1_000_000) as ws:
                    self.ws = ws
                    await ws.send("PASS oauth:" + self.token + "\r\n")
                    await ws.send("NICK " + NICK + "\r\n")
                    await ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands\r\n")
                    await ws.send("JOIN #" + CHANNEL + "\r\n")
                    LOG.info("Connecting to Twitch channel %s as normal viewer", CHANNEL)
                    reminder_task=asyncio.create_task(self.reminder_loop())
                    try:
                        await self.read_irc(ws)
                    finally:
                        reminder_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await reminder_task
            except PermissionError as exc:
                LOG.error("IRC permissions failure: %s", exc)
                return
            except Exception as exc:
                LOG.warning("IRC transport disconnected (%s); reconnecting", type(exc).__name__)
            finally:
                self.ws = None
                self.bridge.live_verified_until=0.0
                self._unknown_session="uncertain-"+uuid4().hex
                self.stream_cache=("",0.0)
                self._disconnect_at=datetime.now(timezone.utc)
                # Pending answers belong to this connection, never a future one.
                for task in list(self._chat_tasks):task.cancel()
                if self._chat_tasks:await asyncio.gather(*self._chat_tasks,return_exceptions=True)
            await asyncio.sleep(12)

    async def read_irc(self,ws):
        async for chunk in ws:
            for line in chunk.split("\r\n"):
                if not line:
                    continue
                if line.startswith("PING "):
                    await ws.send("PONG " + line[5:] + "\r\n")
                    continue
                if " NOTICE #" in line:
                    # A chat command can fail server-side despite websocket
                    # send success; don't silently discard Twitch notices.
                    category="rate_or_content" if any(
                        word in line.lower() for word in ("too quickly","not sent","blocked","rate limit")
                    ) else "general"
                    LOG.warning("Twitch IRC NOTICE received category=%s",category)
                if "Login authentication failed" in line:
                                raise PermissionError("Twitch rejected IRC login")
                if "You are permanently banned" in line:
                                raise PermissionError("Account banned from channel")
                if " PRIVMSG #" not in line:
                    if " CLEARMSG #" in line and line.startswith("@"):
                        tags=parse_tags(line[1:].split(" ",1)[0])
                        mid=tags.get("target-msg-id")
                        if mid:
                            row=self.bridge.db.execute("SELECT stream_id FROM transcript_messages WHERE message_id=?",(mid,)).fetchone()
                            self.bridge.transcript.delete_message(mid)
                            with self.bridge.db:
                                self.bridge.db.execute("DELETE FROM chat_events WHERE message_id=?",(mid,))
                                if row:self.bridge.redact_stream_replies([row[0]])
                    elif " CLEARCHAT #" in line and line.startswith("@"):
                        tags=parse_tags(line[1:].split(" ",1)[0])
                        uid=tags.get("target-user-id")
                        if uid:
                            # A moderation deletion erases existing text, without
                            # permanently opting the account out of future capture.
                            affected=self.bridge.transcript.delete_user(uid)
                            with self.bridge.db:
                                self.bridge.db.execute("DELETE FROM chat_events WHERE twitch_user_id=?",(uid,))
                                self.bridge.redact_stream_replies(affected)
                                analytics_remove_user(self.bridge.db,uid)
                        elif CHANNEL and (" CLEARCHAT #"+CHANNEL) in line:
                            # Twitch full-chat clear: erase every captured stream
                            # for this one-channel database, including derived data.
                            streams=[r[0] for r in self.bridge.db.execute("SELECT stream_id FROM transcript_sessions")]
                            for sid in streams:self.bridge.transcript.delete_stream(sid)
                            with self.bridge.db:
                                self.bridge.db.execute("DELETE FROM chat_events")
                                self.bridge.db.execute("DELETE FROM activity_buckets")
                                self.bridge.db.execute("DELETE FROM activity_message_ids")
                                self.bridge.db.execute("DELETE FROM activity_reply_ids")
                    continue
                event = parse_privmsg(line)
                if not event:
                    continue
                incoming_channel, payload = event
                if incoming_channel != CHANNEL or payload["chatter_user_login"] == NICK:
                    continue
                if payload["room_id"]:
                    self.room_id = payload["room_id"]
                stream=await self.stream_id()
                payload["_stream_id"]=stream
                if self._disconnect_at:
                    self.bridge.transcript.mark_gap(stream,self._disconnect_at,datetime.now(timezone.utc),"IRC disconnected; messages unavailable")
                    self._disconnect_at=None
                if not await self.bridge.observe_public(payload):continue
                payload["_observed"]=True
                # Bound queued AI work while still recording every public line.
                if len(self._chat_tasks)>=32 and not self.bridge.access.is_owner(payload['chatter_user_id']):continue
                task=asyncio.create_task(self.bridge.on_chat(payload))
                self._chat_tasks.add(task)
                task.add_done_callback(self._chat_tasks.discard)

async def main():
    required = ["TWITCH_IRC_NICK", "TWITCH_CHANNEL_LOGIN",
                "ROBORATH_OWNER_TWITCH_USER_ID",
                "ROBORATH_STREAMER_TWITCH_USER_ID"]
    # Allow opt-in conversational/Mario mode before a distinct, nonadmin
    # Mattermost relay account exists. This never enables fact/research.
    if os.getenv("ROBORATH_FACT_RELAY_ENABLED", "false").lower() == "true":
        required += ["MATTERMOST_BOT_TOKEN", "MATTERMOST_CHANNEL_ID"]
    required += (["TWITCH_CLIENT_ID","TWITCH_CLIENT_SECRET"] if TOKEN_FILE
                 else ["TWITCH_IRC_TOKEN"])
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise SystemExit("Not activated; missing required configuration: " + ", ".join(missing))
    if not re.fullmatch(r"[a-z0-9_]{3,25}", NICK):
        raise SystemExit("Invalid TWITCH_IRC_NICK")
    if not re.fullmatch(r"[a-z0-9_]{3,25}", CHANNEL):
        raise SystemExit("Invalid TWITCH_CHANNEL_LOGIN")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    adapter = IRCAdapter()
    try:
        await adapter.run()
    finally:
        await adapter.bridge.http.aclose()
        adapter.bridge.db.close()


if __name__ == "__main__":
    asyncio.run(main())
