import asyncio
import os
import sys
import tempfile
from pathlib import Path

os.environ["TWITCH_IRC_NICK"] = "greenbot"
os.environ["TWITCH_CHANNEL_LOGIN"] = "examplechannel"
with tempfile.TemporaryDirectory() as tmp:
    os.environ["GT_TWITCH_DB"] = str(Path(tmp) / "twitch.sqlite3")
    from irc_adapter import IRCAdapter, parse_tags, parse_privmsg
    assert parse_tags("id=abc;display-name=Name\\sHere") == {"id":"abc","display-name":"Name Here"}
    raw = "@id=abc-123;user-id=1234;room-id=777;display-name=Viewer :viewer!viewer@viewer.tmi.twitch.tv PRIVMSG #examplechannel :!fact Is this correct?"
    channel, event = parse_privmsg(raw)
    assert channel == "examplechannel"
    assert event["message_id"] == "abc-123"
    assert event["chatter_user_id"] == "1234"
    assert event["room_id"] == "777"
    assert event["message"]["text"] == "!fact Is this correct?"
    assert parse_privmsg("PING :tmi.twitch.tv") is None
    class FakeSocket:
        def __init__(self): self.sent = []
        async def send(self, text): self.sent.append(text)
    async def test():
        bridge = IRCAdapter()
        bridge.ws = FakeSocket()
        # The parent snippet no longer renders as a mini-thread by default.
        bridge.bridge.db.execute(
            "INSERT INTO chat_events(message_id,stream_id,twitch_user_id,twitch_login,created_utc,request_text) "
            "VALUES ('abc-123','stream','1234','viewer','2026-11-09T12:00:00Z','!ask hello')")
        bridge.bridge.db.commit()
        await bridge.reply("Evidence suggests the claim is false.", "abc-123")
        assert bridge.ws.sent[0].startswith("PRIVMSG #examplechannel :@viewer ")
        assert "@reply-parent-msg-id=" not in bridge.ws.sent[0]
        assert "false." in bridge.ws.sent[0]
        bridge.room_id = ""
        assert (await bridge.stream_id()).startswith("examplechannel-irc-day-")
        await bridge.bridge.http.aclose()
        bridge.bridge.db.close()
    asyncio.run(test())
print("PASS: IRC tags, message parsing, chat replies, stream fallback")
