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

import httpx
from websockets.asyncio.client import connect
from bridge import Bridge, clean_request
from access_control import requested_capability
from twitch_auth import access_token

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
    if not mid or not uid:
        return None
    return channel.lower(), {
        "message_id": mid,
        "chatter_user_id": uid,
        "chatter_user_login": login.lower(),
        "message": {"text": body},
        "room_id": tags.get("room-id", ""),
    }


def sanitize_public_reply(answer: str, login: str = "") -> str:
    """Strip model hype, duplicate speaker mentions, and decorative clutter."""
    answer=re.sub(r"\s+", " ", str(answer or "")).strip()
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
                        identity = str(streams[0]["id"])
                        self.stream_cache = (identity, time.monotonic() + 60)
                        return identity
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                LOG.warning("Stream lookup unavailable (%s)", type(exc).__name__)
        # Fallback per-channel UTC day; not guaranteed to distinguish 2 streams
        # on the same day. Use Helix stream lookup when client ID is supplied.
        from datetime import datetime, timezone
        identity = CHANNEL + "-irc-day-" + datetime.now(timezone.utc).strftime("%Y%m%d")
        self.stream_cache = (identity, time.monotonic() + 60)
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
        if self.bridge.access.muted():
            raise PermissionError("global mute: no messages may be sent")
        if OWNER_ONLY_TEST:
            if not message_id:
                raise PermissionError("scheduled or anonymous posts disabled in QA")
            row=self.bridge.db.execute(
                "SELECT twitch_user_id,request_text,command FROM chat_events WHERE message_id=?",
                (message_id,)).fetchone()
            if row:
                user_id,request,command=row
                caps={"chat":"conversation","search":"conversation",
                      "fact":"fact","research":"research"}
                capability=caps.get(command) or requested_capability(request)
                if not capability or not self.bridge.access.allowed(user_id,capability):
                    raise PermissionError("Twitch test permission revoked or absent")
            elif message_id not in self.bridge._owner_admin_replies:
                raise PermissionError("unlogged response not authorized in QA")
        # Plain channel replies avoid Twitch's visually confusing mini-thread.
        # Prefix the verified sender's login instead of making the model guess.
        login=""
        if message_id:
            row = self.bridge.db.execute(
                "SELECT twitch_login FROM chat_events WHERE message_id=?",
                (message_id,)).fetchone()
            login = row[0] if row else ""
        answer=sanitize_public_reply(answer,login)
        if not THREADED_REPLIES and re.fullmatch(r"[a-z0-9_]{3,25}",login or "",re.I):
            answer="@"+login+" "+answer
        encoded = answer.encode("utf-8")[:430]
        answer = encoded.decode("utf-8", errors="ignore")
        if not answer:
            return
        async with self.send_lock:
            remaining = MIN_REPLY_INTERVAL - (time.monotonic() - self.last_send)
            if remaining > 0:
                await asyncio.sleep(remaining)
            # Check again after pacing: a mute/revoke may have arrived while a
            # previous model call was generating or the IRC queue was waiting.
            if self.bridge.access.muted():
                raise PermissionError("global mute while reply pending")
            if OWNER_ONLY_TEST and message_id not in self.bridge._owner_admin_replies:
                row=self.bridge.db.execute(
                    "SELECT twitch_user_id,request_text,command FROM chat_events WHERE message_id=?",
                    (message_id,)).fetchone()
                if not row:
                    raise PermissionError("no verified message owner for reply")
                capability={"chat":"conversation","search":"conversation",
                            "fact":"fact","research":"research"}.get(row[2]) or requested_capability(row[1])
                if not capability or not self.bridge.access.allowed(row[0],capability):
                    raise PermissionError("access revoked during in-flight reply")
            reference = message_id if re.fullmatch(r"[A-Za-z0-9-]{1,90}", message_id) else ""
            tag = "@reply-parent-msg-id=" + reference + " " if reference and THREADED_REPLIES else ""
            await self.ws.send(tag + "PRIVMSG #" + CHANNEL + " :" + answer + "\r\n")
            self.last_send = time.monotonic()
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
            if OWNER_ONLY_TEST:
                # Suspend all scheduled posts during owner-only QA, including
                # previously queued reminders to other Twitch users.
                await asyncio.sleep(10)
                continue
            try:
                due = self.bridge.notifications.due(limit=4)
                for reminder_id, user_id, note in due:
                    row=self.bridge.db.execute("""SELECT twitch_login FROM chat_events
                        WHERE twitch_user_id=? ORDER BY created_utc DESC LIMIT 1""",
                        (user_id,)).fetchone()
                    if not row:
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
                    continue
                event = parse_privmsg(line)
                if not event:
                    continue
                incoming_channel, payload = event
                if incoming_channel != CHANNEL or payload["chatter_user_login"] == NICK:
                    continue
                if OWNER_ONLY_TEST and not self.bridge.access.can_receive(
                        payload.get("chatter_user_id",""),
                        payload.get("message",{}).get("text",""),
                        strict=True):
                    continue
                if payload["room_id"]:
                    self.room_id = payload["room_id"]
                asyncio.create_task(self.bridge.on_chat(payload))

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
