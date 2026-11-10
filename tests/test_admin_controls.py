import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bridge
from bridge import Bridge
import irc_adapter
from irc_adapter import IRCAdapter


OWNER="1414798445"
VIEWER="55555"
STRANGER="66666"

class AdminIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.keys=("GT_TWITCH_DB","ROBORATH_OWNER_TWITCH_USER_ID",
                   "ROBORATH_STREAMER_TWITCH_USER_ID","ROBORATH_OWNER_ONLY_TEST_MODE",
                   "ROBORATH_FACT_RELAY_ENABLED")
        self.saved={k:os.environ.get(k) for k in self.keys}
        self.original_db=bridge.DB_PATH
        os.environ["GT_TWITCH_DB"]=str(Path(self.tmp.name)/"chat.sqlite3")
        bridge.DB_PATH=os.environ["GT_TWITCH_DB"]
        os.environ["ROBORATH_OWNER_TWITCH_USER_ID"]=OWNER
        os.environ["ROBORATH_STREAMER_TWITCH_USER_ID"]="88888"
        # This suite exercises explicitly granted preview access. Strict
        # owner-only QA has a separate suite and suppresses even these grants.
        os.environ["ROBORATH_OWNER_ONLY_TEST_MODE"]="false"
        os.environ["ROBORATH_FACT_RELAY_ENABLED"]="false"
        bridge.last_user_call.clear()
        bridge.last_cooldown_notice.clear()
        bridge.last_quota_notice.clear()
        self.bot=Bridge()
        self.bot.router=object()
        self.sent=[]
        self.resolved=[]
        async def send(text,mid):self.sent.append((mid,text))
        async def stream():return "test-stream"
        async def lookup(login):
            self.resolved.append(login)
            if login=="viewerx":return VIEWER,"viewerx"
            if login=="strangerx":return STRANGER,"strangerx"
            raise LookupError("unverified")
        self.bot.twitch_reply=send
        self.bot.stream_id=stream
        self.bot.lookup_twitch_login=lookup

    def tearDown(self):
        asyncio.run(self.bot.http.aclose())
        if self.bot.router and hasattr(self.bot.router,"http"):
            asyncio.run(self.bot.router.http.aclose())
        self.bot.db.close()
        bridge.DB_PATH=self.original_db
        for k,v in self.saved.items():
            if v is None:os.environ.pop(k,None)
            else:os.environ[k]=v
        self.tmp.cleanup()

    def event(self,uid,login,text,mid):
        return {"chatter_user_id":uid,"chatter_user_login":login,
                "message":{"text":text},"message_id":mid}

    def send(self,uid,login,text,mid):
        asyncio.run(self.bot.on_chat(self.event(uid,login,text,mid)))

    def test_english_grant_conversation_then_all_then_revoke(self):
        self.send(OWNER,"joeyleq","roborath, allow @viewerx to use conversation","ownergrant")
        self.assertEqual(self.bot.access.capabilities(VIEWER),{"conversation"})
        self.assertEqual(self.resolved,["viewerx"])
        self.send(VIEWER,"viewerx","!ask how many r's are in strawberry?","ask1")
        self.assertIn("3 occurrences",self.sent[-1][1])
        before=len(self.sent)
        self.send(VIEWER,"viewerx","!fact is the sun a star?","fact-deny")
        self.assertEqual(len(self.sent),before)
        self.send(OWNER,"joeyleq","give @viewerx all AI abilities","allgrant")
        self.assertEqual(self.bot.access.capabilities(VIEWER),{"conversation","fact","research"})
        self.send(OWNER,"joeyleq","revoke @viewerx fact checking abilities","factrevoke")
        self.assertEqual(self.bot.access.capabilities(VIEWER),{"conversation","research"})
        self.send(OWNER,"joeyleq","remove @viewerx from testing","allrevoke")
        self.assertEqual(self.bot.access.capabilities(VIEWER),set())
        before=len(self.sent)
        self.send(VIEWER,"viewerx","!ask how many r's in strawberry?","deniedagain")
        self.assertEqual(len(self.sent),before)

    def test_owner_can_hard_mute_all_and_resume_in_plain_english(self):
        self.send(OWNER,"joeyleq","allow @viewerx to use conversation","grant")
        before=len(self.sent)
        self.send(OWNER,"joeyleq","stop talking, don't reply to anyone","mute")
        self.assertTrue(self.bot.access.muted())
        self.assertEqual(len(self.sent),before) # no acknowledgement
        self.send(VIEWER,"viewerx","!ask count r in strawberry?","blockedviewer")
        self.send(OWNER,"joeyleq","!ask count r in strawberry?","blockedowner")
        self.assertEqual(len(self.sent),before)
        self.assertEqual(self.bot.db.execute(
            "SELECT count(*) FROM chat_events WHERE message_id in ('blockedviewer','blockedowner')").fetchone()[0],0)
        self.send(OWNER,"joeyleq","roborath resume talking","resume")
        self.assertFalse(self.bot.access.muted())
        self.assertEqual(len(self.sent),before+1)
        self.send(VIEWER,"viewerx","!ask how many r's in strawberry?","viewerback")
        self.assertIn("3 occurrences",self.sent[-1][1])

    def test_only_numeric_owner_administers_even_if_login_spoofed(self):
        self.send(STRANGER,"joeyleq","allow @viewerx all AI abilities","spoof1")
        self.assertEqual(self.bot.access.capabilities(VIEWER),set())
        self.send(STRANGER,"joeyleq","stop talking","spoofmute")
        self.assertFalse(self.bot.access.muted())
        self.send(OWNER,"changed_login","allow @viewerx to fact check","realowner")
        self.assertEqual(self.bot.access.capabilities(VIEWER),{"fact"})
        self.send(VIEWER,"viewerx","allow @strangerx all AI abilities","viewerattack")
        self.assertEqual(self.bot.access.capabilities(STRANGER),set())

    def test_ambiguous_account_lookup_fails_closed(self):
        self.send(OWNER,"joeyleq","give @missinguser all AI abilities","badlookup")
        self.assertEqual(self.bot.access.capabilities(STRANGER),set())
        self.assertIn("verification failed",self.sent[-1][1].lower())

    def test_failed_relay_refunds_viewer_quota_and_reports_unavailable(self):
        async def failing_answer(root):
            raise RuntimeError("synthetic provider quota failure")
        async def mm_post(message):
            return "private-test-post"
        from unittest.mock import patch
        self.send(OWNER,"joeyleq","allow @viewerx to fact check","grantfact")
        self.bot.mm_post=mm_post
        self.bot.mm_answer=failing_answer
        os.environ["ROBORATH_FACT_RELAY_ENABLED"]="true"
        with patch.object(bridge,"MM_TOKEN","mock-secret-present"),patch.object(
                bridge,"MM_CHANNEL","mock-private-channel"):
            self.send(VIEWER,"viewerx","!fact Is the Sun a star?","failingfact")
        row=self.bot.db.execute("SELECT status FROM chat_events WHERE message_id='failingfact'").fetchone()
        self.assertEqual(row,("failed",))
        self.assertEqual(self.bot.db.execute(
            "SELECT count(*) FROM rr_consumptions WHERE message_id='failingfact'").fetchone()[0],0)
        self.assertTrue(any("allowance was refunded" in x[1] for x in self.sent))

    def test_fact_quota_not_silent_and_no_duplicate_model_calls(self):
        call_count=[0]
        async def post(prompt):
            call_count[0]+=1
            return "thread-id"
        async def answer(root):
            return "Correct. Source: https://science.nasa.gov"
        async def shortener(text,http,limit=2):
            return text
        self.bot.mm_post=post;self.bot.mm_answer=answer
        self.send(OWNER,"joeyleq","allow @viewerx to fact check","quota-grant")
        os.environ["ROBORATH_FACT_RELAY_ENABLED"]="true"
        with patch.object(bridge,"MM_TOKEN","test-token"),patch.object(
            bridge,"MM_CHANNEL","private-test"),patch.object(
            bridge,"shorten_sources",shortener):
            self.send(VIEWER,"viewerx","!fact Is the Sun a star?","firstfact")
            bridge.last_user_call.pop(VIEWER,None)
            self.send(VIEWER,"viewerx","!fact Is the Moon a star?","secondfact")
        self.assertEqual(call_count[0],1)
        self.assertEqual(self.bot.db.execute("SELECT status FROM chat_events WHERE message_id='secondfact'").fetchone()[0],"quota_denied")
        self.assertTrue(any(mid=="secondfact" and "limit reached" in msg for mid,msg in self.sent))
        self.assertEqual(self.bot.db.execute("SELECT count(*) FROM rr_consumptions WHERE twitch_user_id=?",(VIEWER,)).fetchone()[0],1)

    def test_missing_question_gets_usage_not_silence(self):
        self.send(OWNER,"joeyleq","!ask","usage-owner")
        self.assertTrue(any(mid=="usage-owner" and "Usage" in msg for mid,msg in self.sent))
        self.send(OWNER,"joeyleq","!fact","usage-owner-fact")
        self.assertTrue(any(mid=="usage-owner-fact" and "Usage" in msg for mid,msg in self.sent))

    def test_owner_access_status(self):
        self.send(OWNER,"joeyleq","allow @viewerx to use research","grant")
        self.send(OWNER,"joeyleq","show access","show")
        self.assertIn("@viewerx: research",self.sent[-1][1])


class TransportAclTests(AdminIntegrationTests):
    def test_outgoing_reply_blocked_after_mute_or_revoke(self):
        with patch.object(irc_adapter,"OWNER_ONLY_TEST",True):
            adapter=IRCAdapter()
            class FakeWS:
                def __init__(self):self.sent=[]
                async def send(self,text):self.sent.append(text)
            adapter.ws=FakeWS()
            adapter.last_send=-1e6
            try:
                adapter.bridge.access.change(OWNER,"grant1",VIEWER,"viewerx","conversation",True)
                adapter.bridge.db.execute("""INSERT INTO chat_events
                    (message_id,stream_id,twitch_user_id,twitch_login,created_utc,request_text,status)
                    VALUES ('m1','s',?,'viewerx','2026-11-09T00:00:00Z','!ask hello','observed')""",(VIEWER,))
                adapter.bridge.db.commit()
                asyncio.run(adapter.reply("A normal answer.","m1"))
                self.assertEqual(len(adapter.ws.sent),1)
                adapter.bridge.access.change(OWNER,"revoke1",VIEWER,"viewerx","conversation",False)
                with self.assertRaises(PermissionError):
                    asyncio.run(adapter.reply("This must not leak.","m1"))
                self.assertEqual(len(adapter.ws.sent),1)
                adapter.bridge.access.set_mute(OWNER,"mute1",True)
                with self.assertRaises(PermissionError):
                    asyncio.run(adapter.reply("No messages while silent.","m1"))
                self.assertEqual(len(adapter.ws.sent),1)
            finally:
                adapter.bridge.db.close()
                asyncio.run(adapter.bridge.http.aclose())
                if adapter.bridge.router and hasattr(adapter.bridge.router,"http"):
                    asyncio.run(adapter.bridge.router.http.aclose())


if __name__=="__main__":
    unittest.main()
