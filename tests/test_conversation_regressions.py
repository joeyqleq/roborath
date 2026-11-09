import asyncio
import os
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path

from bridge import Bridge, exact_answer, last_user_call, last_cooldown_notice
import bridge


class ChatRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old_db=os.environ.get("GT_TWITCH_DB")
        self.old_owner=os.environ.get("ROBORATH_OWNER_TWITCH_USER_ID")
        self.old_streamer=os.environ.get("ROBORATH_STREAMER_TWITCH_USER_ID")
        os.environ["GT_TWITCH_DB"]=str(Path(self.tmp.name)/"chat.sqlite3")
        self.old_db_path=bridge.DB_PATH
        bridge.DB_PATH=os.environ["GT_TWITCH_DB"]
        os.environ["ROBORATH_OWNER_TWITCH_USER_ID"]="12345"
        os.environ["ROBORATH_STREAMER_TWITCH_USER_ID"]="67890"
        last_user_call.clear()
        last_cooldown_notice.clear()
        self.bot=Bridge()
        self.out=[]
        async def fake_reply(txt,mid):self.out.append((mid,txt))
        async def fake_stream():return "test-stream"
        self.bot.twitch_reply=fake_reply
        self.bot.stream_id=fake_stream

    def tearDown(self):
        asyncio.run(self.bot.http.aclose())
        self.bot.db.close()
        bridge.DB_PATH=self.old_db_path
        for key,value in (("GT_TWITCH_DB",self.old_db),("ROBORATH_OWNER_TWITCH_USER_ID",self.old_owner),
                          ("ROBORATH_STREAMER_TWITCH_USER_ID",self.old_streamer)):
            if value is None: os.environ.pop(key,None)
            else:os.environ[key]=value
        self.tmp.cleanup()

    def send(self,mid,text,actor="12345",login="joeyleq"):
        return asyncio.run(self.bot.on_chat({"message_id":mid,"chatter_user_id":actor,
                     "chatter_user_login":login,"message":{"text":text}}))

    def test_rapid_owner_off_and_reset_are_not_throttled(self):
        self.send("o1","!rr mario on")
        self.assertTrue(self.bot.mario.active("test-stream"))
        self.send("o2","!rr mario off")
        self.assertFalse(self.bot.mario.active("test-stream"))
        self.send("o3","!rr mario on")
        self.send("o4","!rr mario reset")
        self.assertEqual(self.bot.mario.status("test-stream"),("off",1,0))
        self.assertEqual(len(self.out),4)

    def test_rapid_owner_questions_are_answered(self):
        self.bot.router=object()
        self.send("q1","!ask how many r's are their in strawberry")
        self.send("q2","!ask prove 2+1 is not 3")
        self.assertEqual(len(self.out),2)
        self.assertIn("3 occurrences",self.out[0][1])
        self.assertIn("2 + 1 = 3",self.out[1][1])
        statuses=self.bot.db.execute("SELECT status FROM chat_events WHERE message_id IN ('q1','q2') ORDER BY message_id").fetchall()
        self.assertEqual(statuses,[("answered",),("answered",)])

    def test_viewer_gets_cooldown_notice_instead_of_silent_failure(self):
        self.bot.router=object()
        self.send("v1","!ask prove 2+1 is not 3",actor="55555",login="viewerx")
        self.send("v2","!ask how many r's are there in strawberry",actor="55555",login="viewerx")
        self.assertEqual(len(self.out),2)
        self.assertIn("cooldown",self.out[-1][1])
        status=self.bot.db.execute("SELECT status FROM chat_events WHERE message_id='v2'").fetchone()[0]
        self.assertEqual(status,"rate_limited")

    def test_answer_fails_without_silence(self):
        class BadModel:
            async def complete(self,*args,**kwargs):raise RuntimeError("synthetic failure")
        self.bot.router=BadModel()
        self.send("qfailed","!ask tell me the difference between race cars and karts")
        self.assertEqual(len(self.out),1)
        self.assertIn("failed",self.out[0][1])
        self.assertEqual(self.bot.db.execute("SELECT status FROM chat_events WHERE message_id='qfailed'").fetchone()[0],"failed")

    def test_repeated_strawberry_variants_are_not_model_guesses(self):
        self.bot.router=object()
        for i,q in enumerate((
            "!ask how many r’s are there in strawberry?",
            "!ask how many r’s r there in strawberry?",
            "!ask how many r’s r there in sstrawberry?")):
            self.send("straw"+str(i),q)
        self.assertEqual(len(self.out),3)
        for _,answer in self.out:self.assertIn("3 occurrences",answer)

    def test_previous_bad_answer_self_audit(self):
        self.bot.router=object()
        self.send("good","!ask how many r's are there in strawberry?")
        self.bot.db.execute(
            "INSERT INTO chat_events(message_id,stream_id,twitch_user_id,twitch_login,created_utc,command,request_text,answer_text,status)"
            " VALUES ('bad','test-stream','12345','joeyleq',?,'chat',?,?,'answered')",
            (datetime.now(timezone.utc).isoformat(),
             "!ask how many r's r there in strawberry?", "Six."))
        self.bot.db.commit()
        self.send("audit","!ask analyze your last 3 responses, where is the anomaly?")
        self.assertIn("6 answer was wrong",self.out[-1][1])
        self.assertIn("3 occurrences",self.out[-1][1])

    def test_owner_unprefixed_repeat_count_question(self):
        self.bot.router=object()
        self.send("prefix","!ask how many r's are there in strawberry?")
        self.send("ownerplain","how many r’s r there in strawberry?")
        self.assertEqual(len(self.out),2)
        self.assertIn("3 occurrences",self.out[-1][1])

    def test_factual_video_title_and_followup(self):
        from unittest.mock import patch
        async def fake_video(q,h):
            return ("Latest published upload in The Shmuley Show, 2026-11-05: Correct Official Title",
                    "https://www.youtube.com/watch?v=BBBBBBBBBBB")
        async def fake_shortener(text,h,limit=1):
            return text.replace("https://www.youtube.com/watch?v=BBBBBBBBBBB","https://is.gd/test")
        self.bot.router=object()
        with patch("bridge.newest_video",fake_video),patch("bridge.shorten_sources",fake_shortener):
            self.send("video1","!search what is the latest video for rabbi shmuley called? from his accounts only.")
            self.send("video2","!ask tell me the title name")
        self.assertEqual(len(self.out),2)
        for _,answer in self.out:
            self.assertIn("Correct Official Title",answer)
            self.assertNotIn("Rath's Rumble",answer)

    def test_other_viewer_context_is_never_leaked(self):
        class Recorder:
            def __init__(self):self.kwargs=[]
            async def complete(self,*args,**kw):
                self.kwargs.append(kw)
                return type("Response",(),{"text":"Ordinary answer."})()
        self.bot.router=Recorder()
        self.send("ownersecret","!ask describe my secret keyboard?")
        self.send("otherquestion","!ask what is your favorite keyboard layout?",actor="55555",login="viewerx")
        self.assertEqual(len(self.bot.router.kwargs),2)
        self.assertNotIn("secret keyboard",self.bot.router.kwargs[1]["conversation_context"])

    def test_serialization_orders_rapid_asks(self):
        class Recorder:
            def __init__(self):self.contexts=[]
            async def complete(self,prompt,*args,**kw):
                self.contexts.append(kw["conversation_context"])
                await asyncio.sleep(.02)
                return type("Response",(),{"text":"First reply." if "first" in prompt else "Second reply."})()
        self.bot.router=Recorder()
        async def run():
            def event(mid,q):return {"message_id":mid,"chatter_user_id":"12345","chatter_user_login":"joeyleq","message":{"text":q}}
            await asyncio.gather(
                self.bot.on_chat(event("serial1","!ask first question about keyboards?")),
                self.bot.on_chat(event("serial2","!ask second question about keyboards?")))
        asyncio.run(run())
        self.assertEqual(len(self.bot.router.contexts),2)
        self.assertIn("first question",self.bot.router.contexts[1])

    def test_same_viewer_context_is_passed_to_model(self):
        class Recorder:
            def __init__(self):self.kwargs=[]
            async def complete(self,*args,**kw):
                self.kwargs.append(kw)
                return type("Response",(),{"text":"Yes, I remember the earlier question."})()
        self.bot.router=Recorder()
        self.send("memory1","!ask what are two ways to win a kart race?")
        self.send("memory2","!ask what was your previous answer?")
        self.assertEqual(len(self.bot.router.kwargs),2)
        self.assertIn("two ways",self.bot.router.kwargs[1]["conversation_context"])
        self.assertEqual(self.bot.router.kwargs[1]["quality"],"strong")

    def test_mario_mode_does_not_replace_general_prompt(self):
        class GoodModel:
            def __init__(self):self.tiers=[]
            async def complete(self,*args,**kwargs):
                self.tiers.append(kwargs.get("tier"))
                return type("Response",(),{"text":"Two plus one is three."})()
        r=GoodModel();self.bot.router=r
        self.bot.mario.enable("test-stream")
        self.send("testmath","!ask what is two plus one?")
        self.assertEqual(r.tiers,["chat"])
        self.assertIn("three",self.out[-1][1])


if __name__=="__main__":
    unittest.main()
