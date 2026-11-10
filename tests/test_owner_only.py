import asyncio
import os
import tempfile
import unittest
from pathlib import Path

import bridge
from bridge import Bridge


class OwnerOnlyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.names=("GT_TWITCH_DB","ROBORATH_OWNER_TWITCH_USER_ID",
                    "ROBORATH_STREAMER_TWITCH_USER_ID",
                    "ROBORATH_OWNER_ONLY_TEST_MODE")
        self.saved={n:os.environ.get(n) for n in self.names}
        self.old_path=bridge.DB_PATH
        os.environ["GT_TWITCH_DB"]=str(Path(self.tmp.name)/"chat.sqlite3")
        bridge.DB_PATH=os.environ["GT_TWITCH_DB"]
        os.environ["ROBORATH_OWNER_TWITCH_USER_ID"]="1414798445"
        os.environ["ROBORATH_STREAMER_TWITCH_USER_ID"]="67890"
        os.environ["ROBORATH_OWNER_ONLY_TEST_MODE"]="true"
        self.bot=Bridge()
        self.bot.router=object()  # deterministic count still expects router readiness
        self.replies=[]
        async def reply(message,mid):self.replies.append((mid,message))
        async def stream():return "test-stream"
        self.bot.twitch_reply=reply
        self.bot.stream_id=stream

    def tearDown(self):
        asyncio.run(self.bot.http.aclose())
        if self.bot.router and hasattr(self.bot.router,"http"):
            asyncio.run(self.bot.router.http.aclose())
        self.bot.db.close()
        bridge.DB_PATH=self.old_path
        for name,value in self.saved.items():
            if value is None:os.environ.pop(name,None)
            else:os.environ[name]=value
        self.tmp.cleanup()

    def send(self,id,login,body,mid):
        return asyncio.run(self.bot.on_chat({
            "message_id":mid,"chatter_user_id":id,
            "chatter_user_login":login,"message":{"text":body}}))

    def test_only_numeric_owner_can_get_any_reply(self):
        cases=[
            ("00001","joeyleq","!ask how many r's are there in strawberry?","spoof"),
            ("67890","rath_bone","!rr help","streamer"),
            ("80000","viewer","!privacy","privacy"),
            ("80000","viewer","!rr mario status","mario"),
            ("80000","viewer","!rr remind 1m say hello","reminder"),
        ]
        for id,login,body,mid in cases:
            self.send(id,login,body,mid)
        self.assertEqual(self.replies,[])
        self.assertEqual(self.bot.db.execute("SELECT count(*) FROM chat_events").fetchone()[0],0)
        self.send("1414798445","different_login","!ask how many r's are there in strawberry?","owner")
        self.assertEqual(len(self.replies),1)
        self.assertIn("3 occurrences",self.replies[0][1])

    def test_missing_verified_owner_fails_closed(self):
        os.environ.pop("ROBORATH_OWNER_TWITCH_USER_ID")
        self.send("1414798445","joeyleq","!rr help","owner")
        self.assertEqual(self.replies,[])

    def test_explicit_disable_restores_normal_mode(self):
        os.environ["ROBORATH_OWNER_ONLY_TEST_MODE"]="false"
        self.bot.access.change("1414798445","preview-grant","00001","viewer","conversation",True)
        self.send("00001","viewer","!ask how many r's are there in strawberry?","viewer")
        self.assertEqual(len(self.replies),1)


if __name__=="__main__":
    unittest.main()
