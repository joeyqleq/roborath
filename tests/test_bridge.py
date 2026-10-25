import asyncio, os, tempfile
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path
with tempfile.TemporaryDirectory() as tmp:
    os.environ["GT_TWITCH_DB"] = str(Path(tmp)/"chat.sqlite3")
    os.environ["ROBORATH_OWNER_TWITCH_USER_ID"]="12345"
    os.environ["ROBORATH_STREAMER_TWITCH_USER_ID"]="99999"
    import bridge
    from bridge import Bridge
    async def mock_shortlinks(text, client):
        return text.replace("https://example.org", "https://is.gd/mock")
    bridge.shorten_sources = mock_shortlinks
    async def test():
        bot=Bridge()
        outgoing=[]
        async def stream():return "stream-test-123"
        async def mpost(text):return "mm-thread-1"
        async def answer(root):return "Correct — verified. Source: https://example.org"
        async def reply(text,mid):outgoing.append((mid,text))
        bot.stream_id=stream;bot.mm_post=mpost;bot.mm_answer=answer;bot.twitch_reply=reply
        event=lambda mid,txt:{"message_id":mid,"chatter_user_id":"u123","chatter_user_login":"viewer","message":{"text":txt}}
        await bot.on_chat(event("m1","Hello world"))
        assert bot.db.execute("SELECT count(*) FROM chat_events").fetchone()[0]==1
        bridge.last_user_call.clear()
        # A fresh host may have monotonic uptime below the cooldown.
        with patch.object(bridge, "time", SimpleNamespace(monotonic=lambda: 1.0)):
            await bot.on_chat(event("m2","!fact Test claim?"))
        row=bot.db.execute("SELECT stream_id,status FROM chat_events WHERE message_id='m2'").fetchone()
        assert row==("stream-test-123","answered"),row
        # Untrusted viewer can't create a persistent keyword watch.
        unauthorized={"message_id":"watch1","chatter_user_id":"556",
                      "chatter_user_login":"visitor",
                      "message":{"text":"!rr watch sensitive => alert me"}}
        await bot.on_chat(unauthorized)
        assert bot.db.execute("SELECT count(*) FROM rr_text_watches").fetchone()[0]==0
        # Only the verified owner may create watches or delegate trigger_manage.
        authorized={"message_id":"watch2","chatter_user_id":"12345",
                    "chatter_user_login":"owner",
                    "message":{"text":"!rr watch sensitive => alert me"}}
        await bot.on_chat(authorized)
        assert bot.db.execute("SELECT count(*) FROM rr_text_watches").fetchone()[0]==1
        await bot.on_chat(event("m3","!forgetme"))
        assert bot.db.execute(
            "SELECT count(*) FROM chat_events WHERE twitch_user_id='u123'"
        ).fetchone()[0]==0
        # Other viewers' logs aren't deleted by a single-user opt-out.
        assert bot.db.execute("SELECT count(*) FROM chat_events").fetchone()[0]==2
        assert len(outgoing)==3
        await bot.http.aclose();bot.db.close()
    asyncio.run(test())
print("PASS: stream logging, agent routing, status and privacy deletion")
