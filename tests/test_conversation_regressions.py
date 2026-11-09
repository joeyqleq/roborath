import asyncio
import os
import tempfile
import unittest
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
