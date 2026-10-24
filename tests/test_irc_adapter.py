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
        await bridge.reply("Evidence suggests the claim is false.", "abc-123")
        assert bridge.ws.sent[0].startswith("@reply-parent-msg-id=abc-123 PRIVMSG #examplechannel :")
        assert "false." in bridge.ws.sent[0]
        bridge.room_id = ""
        assert (await bridge.stream_id()).startswith("examplechannel-irc-day-")
        await bridge.bridge.http.aclose()
        bridge.bridge.db.close()
    asyncio.run(test())
print("PASS: IRC tags, message parsing, chat replies, stream fallback")
