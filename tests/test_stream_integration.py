"""Offline end-to-end privacy, output and transport regressions.

No network/provider calls: actual Bridge and IRCAdapter use temporary SQLite.
"""
import asyncio
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import bridge
import irc_adapter
from formatting import UnsafeModelOutput

OWNER="1414798445"
VIEWER="555123"
STREAMER="888123"


class StreamIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.config=patch.dict(os.environ,{
            "ROBORATH_OWNER_TWITCH_USER_ID":OWNER,
            "ROBORATH_STREAMER_TWITCH_USER_ID":STREAMER,
            "ROBORATH_OWNER_ONLY_TEST_MODE":"true",
            "ROBORATH_PUBLIC_ACCESS_ENABLED":"false",
            "ROBORATH_FACT_RELAY_ENABLED":"false",
            "NEBIUS_API_KEY":"","MERGE_API_KEY":"","NVIDIA_API_KEY":""})
        self.config.start()
        self.path=patch.object(bridge,"DB_PATH",str(Path(self.temp.name)/"chat.sqlite3"))
        self.path.start()
        self.adapter=irc_adapter.IRCAdapter()
        self.bot=self.adapter.bridge
        self.frames=[]
        class Socket:
            async def send(inner,frame):self.frames.append(frame)
        self.adapter.ws=Socket()
        self.adapter.last_send=-1e6
        async def stream():return "stream-one"
        self.bot.stream_id=stream
        bridge.last_user_call.clear()

    async def asyncTearDown(self):
        await self.bot.http.aclose()
        self.bot.db.close()
        self.path.stop();self.config.stop();self.temp.cleanup()

    def event(self,mid,text,uid=VIEWER):
        return {"message_id":mid,"chatter_user_id":uid,
            "chatter_user_login":"viewerx" if uid==VIEWER else "joeyleq",
            "message":{"text":text}}

    async def test_capture_every_public_viewer_in_strict_qa_without_ai_or_reply(self):
        for i in range(120):
            await self.bot.on_chat(self.event(str(i),"A shared Mao discussion "+str(i)))
        self.assertEqual(self.bot.db.execute("SELECT COUNT(*) FROM transcript_messages").fetchone()[0],120)
        self.assertEqual(self.bot.db.execute("SELECT COUNT(*) FROM chat_events").fetchone()[0],0)
        self.assertEqual(self.frames,[])

    async def test_optout_before_qa_gate_deletes_all_derived_data_even_when_muted(self):
        await self.bot.on_chat(self.event("old","Mao discussion"))
        self.bot.access.set_mute(OWNER,"mute",True)
        await self.bot.on_chat(self.event("forget","!forgetme"))
        await self.bot.on_chat(self.event("new","must not be stored"))
        self.assertEqual(self.bot.transcript.search("stream-one","Mao"),[])
        self.assertEqual(self.bot.db.execute("SELECT count(*) FROM activity_buckets WHERE twitch_user_id=?",(VIEWER,)).fetchone()[0],0)
        self.assertTrue(self.bot.transcript.is_opted_out(VIEWER))
        self.assertEqual(self.frames,[])
        await self.bot.on_chat(self.event("optin","!optin"))
        await self.bot.on_chat(self.event("after","captured while muted"))
        self.assertEqual(self.bot.db.execute("SELECT count(*) FROM transcript_messages").fetchone()[0],1)
        self.assertEqual(self.frames,[])

    async def test_grant_and_streamer_never_bypass_strict_mode(self):
        self.bot.access.change(OWNER,"grant",VIEWER,"viewerx","all",True)
        for uid in (VIEWER,STREAMER):
            await self.bot.on_chat(self.event(uid,"!ask how many r are in strawberry?",uid))
        self.assertEqual(self.frames,[])
        await self.bot.on_chat(self.event("owner","!ask how many r are in strawberry?",OWNER))
        self.assertEqual(len(self.frames),1)
        self.assertIn("3 occurrences",self.frames[0])

    async def test_duplicate_message_invokes_no_second_answer_or_archive(self):
        event=self.event("repeat","!ask how many r are in strawberry?",OWNER)
        await self.bot.on_chat(dict(event))
        await self.bot.on_chat(dict(event))
        self.assertEqual(len(self.frames),1)
        self.assertEqual(self.bot.db.execute("SELECT COUNT(*) FROM transcript_messages").fetchone()[0],2)
        self.assertEqual(self.bot.db.execute("SELECT COUNT(*) FROM transcript_messages WHERE twitch_user_id='1591621882'").fetchone()[0],1)

    async def test_owner_wake_phrase_controls_actual_wire_without_model(self):
        await self.bot.on_chat(self.event("silence","!ask stop replying unless I say banana",OWNER))
        await self.bot.on_chat(self.event("apple","!ask apple",OWNER))
        await self.bot.on_chat(self.event("spoof","banana",VIEWER))
        self.assertEqual(self.frames,[])
        self.assertTrue(self.bot.access.muted())
        await self.bot.on_chat(self.event("wake","banana",OWNER))
        self.assertFalse(self.bot.access.muted())
        self.assertEqual(len(self.frames),1)
        self.assertIn("Captain",self.frames[0])

    async def test_numbered_invokes_share_budget_and_refund_failed_answers(self):
        self.bot.access.invokes.apply(OWNER,'numbered',[VIEWER],'set',2,'stream-one')
        for i in range(3):
            self.adapter.last_send=-1e6
            bridge.last_user_call.clear()
            await self.bot.on_chat(self.event('limited'+str(i),'!ask how many r are in strawberry?'))
        self.assertEqual(sum('3 occurrences' in f for f in self.frames),2)
        self.assertIn('used up',self.frames[-1])

    async def test_bulk_owner_command_resolves_all_before_mutating(self):
        async def lookup(name):
            if name=='missinguser':raise LookupError('missing')
            return VIEWER,'viewerx'
        self.bot.lookup_twitch_login=lookup
        await self.bot.on_chat(self.event('bulk','!ask allow viewerx and missinguser',OWNER))
        self.assertIsNone(self.bot.access.invokes.access(VIEWER))
        self.assertIn('unchanged',self.frames[-1])

    async def test_actual_natural_global_grant_creates_allowance_without_model(self):
        await self.bot.on_chat(self.event('naturalglobal','!ask give invoke permissions to all',OWNER))
        self.assertTrue(self.bot.access.can_receive(VIEWER,'!ask hello',True))
        self.assertEqual(self.bot.access.invokes.limit(VIEWER,'stream-one'),2)
        await self.bot.on_chat(self.event('naturalglobal','!ask give invoke permissions to all',OWNER))
        self.assertEqual(self.bot.access.invokes.limit(VIEWER,'stream-one'),2)
        self.assertTrue(any('2 extra invokes' in f for f in self.frames))

    async def test_global_off_blocks_pending_viewer_send(self):
        self.bot.access.invokes.apply(OWNER,'open',['*'],'allow',None,'stream-one')
        await self.bot.on_chat(self.event('beforeoff','!rr help'))
        self.bot.access.invokes.apply(OWNER,'close',['*'],'global_off',None,'stream-one')
        with self.assertRaises(PermissionError):await self.adapter.reply('must not send','beforeoff')
        self.assertTrue(self.bot.access.can_receive(OWNER,'!ask hello',True))

    async def test_authorized_theme_exception_remains_mutable_at_wire_boundary(self):
        self.bot.theme.activate();self.bot.theme.observe('stream-one',True)
        self.bot.live_stream={'id':'stream-one'};self.bot.live_verified_until=time.monotonic()+60
        key='theme:stream-one';self.bot._theme_posts.add(key)
        await self.adapter.reply('A topical political joke.',key)
        self.assertEqual(len(self.frames),1)
        self.bot.access.set_mute(OWNER,'mutetheme',True)
        with self.assertRaises(PermissionError):await self.adapter.reply('Blocked.',key)
        self.bot.access.set_mute(OWNER,'unmutetheme',False)
        self.bot.theme.stop()
        with self.assertRaises(PermissionError):await self.adapter.reply('Blocked.',key)

    async def test_owner_status_and_access_reports_work_while_muted(self):
        self.bot.access.invokes.apply(OWNER,'globaloff',[],'global_off',None,'stream-one')
        self.bot.access.set_mute(OWNER,'silence',True)
        await self.bot.on_chat(self.event('status','!rr status',OWNER))
        self.assertIn('MUTED',self.frames[-1])
        self.adapter.last_send=-1e6
        await self.bot.on_chat(self.event('accessreport','!ask who is currently allowed to use you?',OWNER))
        self.assertIn('Owner always allowed',self.frames[-1])
        before=len(self.frames)
        await self.bot.on_chat(self.event('fakeaccess','!rr status'))
        self.assertEqual(len(self.frames),before)

    async def test_owner_taught_notes_are_scoped_context_and_can_be_removed(self):
        await self.bot.on_chat(self.event('teach','!rr remember music => System of a Down is our favourite',OWNER))
        self.assertIn('System of a Down',self.bot.shared_chat_context('stream-one','music','new'))
        self.assertNotIn('System of a Down',self.bot.shared_chat_context('another','astronomy','new'))
        self.adapter.last_send=-1e6
        await self.bot.on_chat(self.event('unteach','!rr forget music',OWNER))
        self.assertEqual(self.bot.db.execute('SELECT COUNT(*) FROM rr_owner_notes').fetchone()[0],0)

    async def test_hours_old_word_counts_and_first_speech_are_exact_not_join_time(self):
        start=datetime.now(timezone.utc)-timedelta(hours=3)
        self.bot.transcript.record('stream-one','first-long-ago',VIEWER,'viewerx','one two three',start)
        self.bot.transcript.record('stream-one','second-long-ago',VIEWER,'viewerx','four five',start+timedelta(hours=1))
        answer=self.bot.transcript.activity_question('stream-one','how many words did user viewerx say from the beginning?')
        self.assertIn('2 captured messages, 5 words',answer)
        self.assertIn('3h 0m ago',answer)
        join=self.bot.transcript.activity_question('stream-one','what time did user viewerx come into the stream?')
        self.assertIn('not join time',join)
        self.bot.transcript.delete_message('second-long-ago')
        self.assertIn('1 captured messages, 3 words',self.bot.transcript.activity_question('stream-one','how many words did viewerx say?'))

    async def test_unified_ask_fact_runs_specialist_once(self):
        os.environ['ROBORATH_FACT_RELAY_ENABLED']='true'
        calls=[]
        async def post(prompt):calls.append(prompt);return 'private-root'
        async def answer(root):return 'Yes, confirmed with a source. https://is.gd/fixture'
        async def shorten(text,http,limit=2):return text
        self.bot.mm_post=post;self.bot.mm_answer=answer
        with patch.object(bridge,'MM_TOKEN','fixture'),patch.object(bridge,'MM_CHANNEL','fixture'),patch.object(bridge,'shorten_sources',shorten):
            await self.bot.on_chat(self.event('unifiedfact','!ask verify this historical claim',OWNER))
        self.assertEqual(len(calls),1)
        self.assertEqual(self.bot.db.execute('SELECT command,status FROM chat_events WHERE message_id=?',('unifiedfact',)).fetchone(),('fact','answered'))

    async def test_word_leaderboard_uses_saved_content_without_model(self):
        self.bot.transcript.record('stream-one','leader-one','123','alice','one two three four')
        self.bot.transcript.record('stream-one','leader-two','456','bobby','@alice one two')
        answer=self.bot.transcript.activity_question('stream-one','who here has spoken the most?')
        self.assertIn('1. @alice 4',answer)
        self.assertIn('2. @bobby 2',answer)
        self.assertIn('top by words',answer)
        self.assertNotIn('alice',self.bot.transcript.activity_question('other-stream','leaderboard'))

    async def test_real_typo_and_said_word_count_query_does_not_fall_through_to_model(self):
        self.bot.transcript.record('stream-one','said-first','123','saeedmsr','one two three')
        await self.bot.on_chat(self.event('realwordquery',"!ask howw many words has SAEEDMSR said so far since the beginning of the stream? what's his rank?",OWNER))
        self.assertIn('3 words',self.frames[-1])
        self.assertIn('Rank #',self.frames[-1])
        self.assertNotIn("don't have access",self.frames[-1])

    async def test_self_reference_uses_authenticated_user_without_spending_a_clarification(self):
        self.bot.transcript.record('stream-one','self-first',VIEWER,'viewerx','one two three')
        self.bot.access.invokes.apply(OWNER,'self-grant',[VIEWER],'set',4,'stream-one')
        await self.bot.on_chat(self.event('mywords',"!ask how many words did I say so far? what's my rank?"))
        self.assertIn('words',self.frames[-1]);self.assertIn('Rank #',self.frames[-1])
        self.assertNotIn('Which Twitch username',self.frames[-1])
        self.assertEqual(self.bot.db.execute("SELECT status FROM chat_events WHERE message_id='mywords'").fetchone()[0],'answered')
        self.adapter.last_send=-1e6;bridge.last_user_call.clear()
        await self.bot.on_chat(self.event('nobody','!ask how many words overall?'))
        self.assertEqual(self.bot.db.execute("SELECT COUNT(*) FROM rr_invoke_usage WHERE user_id=? AND used=1",(VIEWER,)).fetchone()[0],1)

    async def test_intake_words_reply_counts_and_clean_private_export(self):
        event=self.event("public","hello fellow chat")
        event['reply_parent_user_id']=OWNER
        await self.bot.on_chat(event)
        await self.bot.on_chat(self.event("own","!ask how many r are in strawberry?",OWNER))
        row=self.bot.db.execute("SELECT message_count,word_count,native_reply_count,bot_reply_count FROM activity_buckets WHERE twitch_user_id=?",(VIEWER,)).fetchone()
        self.assertEqual(row,(1,3,1,0))
        self.assertEqual(self.bot.db.execute("SELECT bot_reply_count FROM activity_buckets WHERE twitch_user_id=?",(OWNER,)).fetchone()[0],1)
        from report import render
        exported=render(self.bot.db,"transcript","stream-one")
        self.assertIn("viewerx: hello fellow chat",exported)
        self.assertIn("3 occurrences",exported)
        self.assertNotIn("PRIVMSG",exported)

    async def test_fact_permission_is_checked_after_command_prefix_removed(self):
        os.environ['ROBORATH_OWNER_ONLY_TEST_MODE']='false'
        self.bot.access.change(OWNER,'fact-grant',VIEWER,'viewerx','fact',True)
        with self.bot.db:
            self.bot.db.execute("INSERT INTO chat_events(message_id,stream_id,twitch_user_id,twitch_login,created_utc,command,request_text,status) VALUES (?,?,?,?,?,'fact',?,'pending')",('fact-answer','stream-one',VIEWER,'viewerx',datetime.now(timezone.utc).isoformat(),'Earth orbits Sun'))
        await self.adapter.reply('Yes. https://is.gd/example','fact-answer')
        self.assertEqual(len(self.frames),1)
        self.bot.access.change(OWNER,'fact-revoke',VIEWER,'viewerx','fact',False)
        with self.assertRaises(PermissionError):await self.adapter.reply('Late answer','fact-answer')

    async def test_search_followup_uses_prior_question_instead_of_literal_command(self):
        self.bot.db.execute("INSERT INTO chat_events(message_id,stream_id,twitch_user_id,twitch_login,created_utc,command,request_text,answer_text,status) VALUES (?,?,?,?,?,'chat',?,?, 'answered')",('earlier','stream-one',OWNER,'joeyleq',datetime.now(timezone.utc).isoformat(),'!ask who founded the Python Software Foundation?','I am not sure.'))
        self.bot.db.commit()
        captured=[]
        async def fake_lookup(question,http,forced=False):
            captured.append((question,forced));return ('Search leads only: Python https://is.gd/psf','python.org')
        async def fake_shorten(text,http,limit=2):return text
        with patch('bridge.lookup',fake_lookup),patch('bridge.shorten_sources',fake_shorten):
            await self.bot.on_chat(self.event('follow','!ask incorrect. search the web',OWNER))
        self.assertEqual(captured,[('who founded the Python Software Foundation?',True)])

    async def test_moderation_clear_removes_captured_and_derived_bot_text(self):
        await self.bot.on_chat(self.event('user-history','some public words'))
        await self.bot.on_chat(self.event('owner-history','!ask how many r are in strawberry?',OWNER))
        class Incoming:
            def __aiter__(self):return self
            async def __anext__(self):
                if getattr(self,'done',False):raise StopAsyncIteration
                self.done=True
                return '@target-user-id='+VIEWER+' :tmi.twitch.tv CLEARCHAT #'+irc_adapter.CHANNEL+' :viewerx\r\n'
        await self.adapter.read_irc(Incoming())
        self.assertFalse(self.bot.transcript.is_opted_out(VIEWER))
        self.assertEqual(self.bot.db.execute("SELECT COUNT(*) FROM transcript_messages WHERE twitch_user_id IN (?, '1591621882')",(VIEWER,)).fetchone()[0],0)

    async def test_actual_historical_tool_leak_is_blocked_at_final_transport(self):
        await self.bot.on_chat(self.event("ordinary","!rr help",OWNER))
        before=len(self.frames)
        for artifact in ('<think> {"name": "search_tools", "arguments": {"query": "history"}} </tool_call>',
                         '{"name":"browser","arguments":{}}',
                         '&lt;think&gt;private reasoning&lt;/think&gt;'):
            with self.assertRaises(UnsafeModelOutput):
                await self.adapter.reply(artifact,"ordinary")
        self.assertEqual(len(self.frames),before)

    async def test_mute_while_waiting_for_pacing_blocks_wire_send(self):
        await self.bot.on_chat(self.event("queued","!rr help",OWNER))
        before=len(self.frames)
        self.adapter.last_send=time.monotonic()
        async def mute_during_wait(delay):self.bot.access.set_mute(OWNER,"mute-inflight",True)
        with patch.object(irc_adapter.asyncio,"sleep",mute_during_wait):
            with self.assertRaises(PermissionError):await self.adapter.reply("should disappear","queued")
        self.assertEqual(len(self.frames),before)

    async def test_revoke_while_waiting_for_pacing_blocks_wire_send(self):
        os.environ["ROBORATH_OWNER_ONLY_TEST_MODE"]="false"
        self.bot.access.change(OWNER,"grant",VIEWER,"viewerx","conversation",True)
        await self.bot.on_chat(self.event("queued","!rr help"))
        before=len(self.frames)
        self.adapter.last_send=time.monotonic()
        async def revoke_during_wait(delay):self.bot.access.change(OWNER,"revoke",VIEWER,"viewerx","all",False)
        with patch.object(irc_adapter.asyncio,"sleep",revoke_during_wait):
            with self.assertRaises(PermissionError):await self.adapter.reply("should disappear","queued")
        self.assertEqual(len(self.frames),before)

    async def test_three_hour_shared_memory_is_literal_attributed_and_local(self):
        when=datetime.now(timezone.utc)-timedelta(hours=3)
        self.bot.transcript.record("stream-one","historical",VIEWER,"viewerx","Mao discussion: the date was corrected",when)
        self.bot.transcript.record("other-stream","other",VIEWER,"viewerx","private-to-another-stream",when)
        await self.bot.on_chat(self.event("lookup","!ask What did user viewerx say 3 hours ago?",OWNER))
        self.assertEqual(len(self.frames),1)
        self.assertIn("@viewerx",self.frames[0]);self.assertIn("date was corrected",self.frames[0])
        self.assertNotIn("private-to-another-stream",self.frames[0])
        self.assertIn("gaps",self.frames[0])

    async def test_scheduled_posts_require_verified_live_status_and_public_mode(self):
        with self.assertRaises(PermissionError):await self.adapter.reply("Follow Rath","")
        os.environ["ROBORATH_OWNER_ONLY_TEST_MODE"]="false"
        with self.assertRaises(PermissionError):await self.adapter.reply("Follow Rath","")
        self.bot.live_stream={"id":"stream-one"};self.bot.live_verified_until=time.monotonic()+60
        await self.adapter.reply("Follow Rath","")
        self.assertEqual(len(self.frames),1)

    async def test_synthetic_incomplete_verify_consumes_no_quota(self):
        await self.bot.on_chat(self.event("incomplete","!verify",OWNER))
        self.assertIn("Usage:",self.frames[0])
        self.assertEqual(self.bot.db.execute("SELECT COUNT(*) FROM rr_consumptions").fetchone()[0],0)

    def test_server_timestamp_is_preserved(self):
        result=irc_adapter.parse_privmsg('@id=abc;user-id=555123;tmi-sent-ts=1794283200000 :viewerx!v@v PRIVMSG #rath_bone :hello')
        self.assertEqual(result[1]['created_utc'],datetime.fromtimestamp(1794283200,timezone.utc).isoformat())


if __name__=='__main__':unittest.main()
