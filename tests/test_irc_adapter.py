import asyncio
import os
import sys
import tempfile
from pathlib import Path

os.environ["TWITCH_IRC_NICK"] = "greenbot"
os.environ["TWITCH_CHANNEL_LOGIN"] = "examplechannel"
os.environ["ROBORATH_OWNER_TWITCH_USER_ID"] = "1414798445"
os.environ["ROBORATH_OWNER_ONLY_TEST_MODE"] = "false"
with tempfile.TemporaryDirectory() as tmp:
    os.environ["GT_TWITCH_DB"] = str(Path(tmp) / "twitch.sqlite3")
    import bridge as bridge_module
    old_db_path=bridge_module.DB_PATH
    bridge_module.DB_PATH=os.environ["GT_TWITCH_DB"]
    import irc_adapter as ia
    old_nick,old_channel,old_test=ia.NICK,ia.CHANNEL,ia.OWNER_ONLY_TEST
    ia.NICK,ia.CHANNEL,ia.OWNER_ONLY_TEST="greenbot","examplechannel",False
    from irc_adapter import IRCAdapter, parse_tags, parse_privmsg, sanitize_public_reply
    text=sanitize_public_reply("Hey @viewer! @viewer ready for Mario? #MK8DX 🏁 🎮", "viewer")
    assert "@viewer" not in text
    assert "#MK8DX" not in text and "🏁" not in text and "🎮" not in text
    assert sanitize_public_reply("You can't prove that.", "viewer").startswith("You can't")
    assert "What's on your mind" not in sanitize_public_reply(
        "Nothing much. What's on your mind?", "viewer")

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
        bridge.bridge.access.change("1414798445","fixture-grant","1234","viewer","conversation",True)
        # The parent snippet no longer renders as a mini-thread by default.
        bridge.bridge.db.execute(
            "INSERT INTO chat_events(message_id,stream_id,twitch_user_id,twitch_login,created_utc,request_text) "
            "VALUES ('abc-123','stream','1234','viewer','2026-11-09T12:00:00Z','!ask hello')")
        bridge.bridge.db.execute(
            "UPDATE chat_events SET status='observed' WHERE message_id='abc-123'")
        bridge.bridge.db.commit()
        await bridge.reply("Evidence suggests the claim is false.", "abc-123")
        row=bridge.bridge.db.execute(
            "SELECT command,answer_text,status FROM chat_events WHERE message_id='abc-123'").fetchone()
        assert row[0]=='control' and row[2]=='answered' and 'false' in row[1]
        assert bridge.ws.sent[0].startswith("PRIVMSG #examplechannel :@viewer ")
        assert "@reply-parent-msg-id=" not in bridge.ws.sent[0]
        assert "false." in bridge.ws.sent[0]
        await bridge.reply("Hey @viewer, @viewer: Mario mode is off. #MK8DX 🏁", "abc-123")
        sent=bridge.ws.sent[-1]
        assert sent.count("@viewer")==1,sent
        assert "#MK8DX" not in sent and "🏁" not in sent
        bridge.room_id = ""
        assert (await bridge.stream_id()).startswith("uncertain-")
        await bridge.bridge.http.aclose()
        bridge.bridge.db.close()
    try:
        asyncio.run(test())
    finally:
        bridge_module.DB_PATH=old_db_path
        ia.NICK,ia.CHANNEL,ia.OWNER_ONLY_TEST=old_nick,old_channel,old_test
print("PASS: IRC tags, message parsing, chat replies, stream fallback")
