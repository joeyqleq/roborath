#!/usr/bin/env python3
"""Unprivileged Twitch IRC chat-client transport for Dr. Greenthumb.

Uses a user OAuth token with only chat:read + chat:edit granted via a trusted
registered client. No Twitch developer application or channel moderator role
is needed. The IRC adapter reuses Bridge's routing, per-viewer memory, consent,
cooldowns, and Mattermost integration.
"""
import asyncio
import json
import logging
import os
import re
import time

import httpx
from websockets.asyncio.client import connect
from bridge import Bridge, clean_request
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


class IRCAdapter:
    def __init__(self):
        self.bridge = Bridge()
        self.ws = None
        self.token = TOKEN
        self.send_lock = asyncio.Lock()
        self.last_send = 0.0
        self.room_id = ""
        self.stream_cache = ("", 0.0)
        self.bridge.twitch_reply = self.reply
        self.bridge.stream_id = self.stream_id

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

    async def reply(self, answer, message_id):
        if not self.ws:
            raise ConnectionError("IRC socket not connected")
        # Twitch IRC messages are limited; enforce UTF-8 byte limit.
        answer = re.sub(r"\s+", " ", answer).strip()
        encoded = answer.encode("utf-8")[:430]
        answer = encoded.decode("utf-8", errors="ignore")
        if not answer:
            return
        async with self.send_lock:
            remaining = MIN_REPLY_INTERVAL - (time.monotonic() - self.last_send)
            if remaining > 0:
                await asyncio.sleep(remaining)
            reference = message_id if re.fullmatch(r"[A-Za-z0-9-]{1,90}", message_id) else ""
            tag = "@reply-parent-msg-id=" + reference + " " if reference else ""
            await self.ws.send(tag + "PRIVMSG #" + CHANNEL + " :" + answer + "\r\n")
            self.last_send = time.monotonic()

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
                    async for chunk in ws:
                        for line in chunk.split("\r\n"):
                            if not line:
                                continue
                            if line.startswith("PING "):
                                await ws.send("PONG " + line[5:] + "\r\n")
                                continue
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
                            if payload["room_id"]:
                                self.room_id = payload["room_id"]
                            asyncio.create_task(self.bridge.on_chat(payload))
            except PermissionError as exc:
                LOG.error("IRC permissions failure: %s", exc)
                return
            except Exception as exc:
                LOG.warning("IRC transport disconnected (%s); reconnecting", type(exc).__name__)
            finally:
                self.ws = None
            await asyncio.sleep(12)


async def main():
    required = ["TWITCH_IRC_NICK", "TWITCH_CHANNEL_LOGIN",
                "MATTERMOST_BOT_TOKEN", "MATTERMOST_CHANNEL_ID",
                "ROBORATH_OWNER_TWITCH_USER_ID",
                "ROBORATH_STREAMER_TWITCH_USER_ID"]
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
