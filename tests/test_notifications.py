import sqlite3
import unittest
from datetime import datetime,timezone,timedelta
from notifications import Notifications,parse_duration,parse_automation_control,FOLLOW_BANK

class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.n=Notifications(self.db)
        self.now=datetime(2026,10,24,12,0,tzinfo=timezone.utc)
    def tearDown(self):self.db.close()
    def test_durations_and_reminders(self):
        self.assertEqual(parse_duration("20m"),1200)
        self.assertEqual(parse_duration("2h"),7200)
        self.assertIsNone(parse_duration("900d"))
        ident=self.n.add_reminder("u1","s1","20m","check result",self.now)
        self.assertEqual(self.n.due(self.now),[])
        due=self.n.due(self.now+timedelta(minutes=20))
        self.assertEqual(due[0][0],ident)
        self.n.delivered(ident,self.now+timedelta(minutes=20))
        self.assertEqual(self.n.due(self.now+timedelta(hours=1)),[])
    def test_watch_stream_scoping(self):
        ident=self.n.watch("u1","s1","hormuz","reply",self.now)
        self.assertEqual(self.n.scan("s2","hormuz",self.now),[])
        self.assertEqual(self.n.scan("s1","hormuz",self.now),[(ident,"u1","reply")])
        self.assertEqual(self.n.scan("s1","hormuz",self.now+timedelta(minutes=1)),[])
        self.assertEqual(len(self.n.scan("s1","hormuz",self.now+timedelta(minutes=6))),1)
        self.assertEqual(self.n.scan("s1","hormuz",self.now+timedelta(hours=13)),[])

    def test_owner_one_time_reply_aliases_stream_expiry_restart_and_replay(self):
        self.n.owner_id='999'
        with self.assertRaises(PermissionError):self.n.arm_once('123','s1','bit',('x123',),'A scripted joke',self.now)
        self.n.arm_once('999','s1','bit',('x123','X one two three'),'A scripted joke',self.now)
        self.assertIsNone(self.n.take_once('123','s1','spoof','x123',self.now))
        self.assertIsNone(self.n.take_once('999','s2','other-stream','x123',self.now))
        self.assertIsNone(self.n.take_once('999','s1','partial','x1234',self.now))
        self.assertEqual(self.n.take_once('999','s1','trigger','!ask X, one two three!',self.now),'A scripted joke')
        restarted=Notifications(self.db,owner_id='999')
        self.assertEqual(restarted.take_once('999','s1','trigger','x123',self.now),'')
        self.assertIsNone(restarted.take_once('999','s1','again','x123',self.now))
        restarted.arm_once('999','s1','late',('x123',),'Expired joke',self.now)
        self.assertIsNone(restarted.take_once('999','s1','late','x123',self.now+timedelta(hours=2)))
        restarted.forget('999')
        self.assertEqual(self.db.execute('SELECT count(*) FROM rr_once_replies').fetchone()[0],0)
    def test_forget_and_limits(self):
        for i in range(5):self.n.add_reminder("u1","s1","1h",str(i),self.now)
        with self.assertRaises(ValueError):
            self.n.add_reminder("u1","s1","1h","over",self.now)
        self.n.watch("u1","s1","mario","alert",self.now)
        self.n.forget("u1")
        self.assertEqual(self.n.db.execute("select count(*) from rr_reminders").fetchone()[0],0)
        self.assertEqual(self.n.db.execute("select count(*) from rr_text_watches").fetchone()[0],0)
    def test_reminder_iso_listing_cancellation_and_permissions(self):
        self.n.owner_id="999"
        ident=self.n.add_reminder("12","s1","1h","check this",self.now)
        self.assertEqual(len(self.n.list_reminders("12")),1)
        self.assertFalse(self.n.cancel_reminder(ident,"13"))
        self.assertTrue(self.n.cancel_reminder(ident,"12",self.now))
        self.assertEqual(self.n.due(self.now+timedelta(days=1)),[])
        due=self.n.add_reminder_at("12","s1", "2026-10-24T15:00:00Z", "fixed",self.now)
        self.assertEqual(self.n.list_reminders("999",owner=True)[0][0],due)
        with self.assertRaises(PermissionError): self.n.list_reminders("12",owner=True)
        with self.assertRaises(PermissionError): self.n.cancel_reminder(due,"12",owner=True)

    def test_owner_rules_and_punctuation_whole_words(self):
        self.n.owner_id="999"
        with self.assertRaises(PermissionError): self.n.add_rule("888","phone","phone","knock knock")
        self.n.add_rule("999","phone","phone","knock knock")
        self.assertEqual(self.n.scan_rules("s1","m1","headphone rang",self.now),[])
        fired=self.n.scan_rules("s1","m2","PHONE! is ringing",self.now)
        self.assertEqual(fired[0][2],"knock knock")
        self.assertEqual(self.n.scan_rules("s1","m3","phone again",self.now+timedelta(seconds=30)),[])
        self.assertEqual(len(self.n.manage_rule("999","list",None)),1)
        self.n.manage_rule("999","disable","phone")
        self.assertEqual(self.n.scan_rules("s1","m4","phone",self.now+timedelta(minutes=6)),[])
        self.n.manage_rule("999","enable","phone")
        self.n.manage_rule("999","remove","phone")
        self.assertEqual(self.n.manage_rule("999","list",None),[])

    def test_five_hour_stream_has_unique_twenty_minute_promotions(self):
        self.n.start_stream("long",self.now)
        sent=[]
        for tick in range(1,16):
            result=self.n.follow_tick("long",self.now+timedelta(minutes=20*tick),live=True)
            self.assertIsNotNone(result)
            self.assertIsNone(self.n.follow_tick("long",self.now+timedelta(minutes=20*tick),live=True))
            sent.append(result)
        self.assertEqual(len(sent),15)
        self.assertEqual(len(set(sent)),15)
        self.assertIsNotNone(self.n.follow_tick("long",self.now+timedelta(hours=5,minutes=20),live=True))

    def test_chat_controls_and_welcome_once_per_stream(self):
        self.n.owner_id="999"
        first=self.n.handle_control("When someone speaks for the first time in a stream, say hello, newcomer", "999", "s1", "ctl1", self.now)
        self.assertIn("saved", first)
        self.assertIsNone(self.n.handle_control("When someone speaks for the first time in a stream, say hello, newcomer", "999", "s1", "ctl1", self.now))
        self.assertEqual(self.n.process_chat("s1","123","viewer","msg1","hi",now=self.now),["hello, newcomer"])
        self.assertEqual(self.n.process_chat("s1","123","viewer","msg2","hi again",now=self.now+timedelta(seconds=1)),[])
        self.assertEqual(self.n.process_chat("s2","123","viewer","msg3","hi",now=self.now+timedelta(hours=1)),["hello, newcomer"])
        self.assertEqual(self.n.process_chat("s3","456","other","msg4","hello",muted=True,now=self.now),[])

    def test_owner_controlled_alarm_list_cancel_and_rule_sample(self):
        self.n.owner_id="999"
        ident=self.n.add_reminder("999","s1","1h","test alarm",self.now)
        listing=self.n.handle_control("!rr reminders", "999", "s1", "cmd1", self.now)
        self.assertIn("#"+str(ident),listing)
        self.assertIn("cancelled",self.n.handle_control("!rr reminder cancel "+str(ident),"999","s1","cmd2",self.now))
        self.n.add_rule("999","phone","phone","knock knock")
        self.assertIn("matches",self.n.handle_control("!rr rule test phone phone!", "999","s1","cmd3",self.now))
        with self.assertRaises(PermissionError): self.n.handle_control("!rr rule remove phone","123","s1","cmd4",self.now)

    def test_first_chat_welcome_obeys_global_rule_delivery_cooldown(self):
        self.n.owner_id="999"
        self.n.set_welcome("999", "welcome")
        self.assertEqual(self.n.process_chat("s1", "123", "first", "m1", "hello", now=self.now), ["welcome"])
        self.assertEqual(self.n.process_chat("s1", "456", "second", "m2", "hello", now=self.now+timedelta(seconds=30)), [])
        self.assertEqual(self.n.process_chat("s1", "789", "third", "m3", "hello", now=self.now+timedelta(minutes=1)), ["welcome"])

    def test_unverified_live_tick_is_consumed_without_later_catchup(self):
        self.n.start_stream("s1", self.now)
        self.assertIsNone(self.n.follow_tick("s1", self.now+timedelta(minutes=20), live=False))
        self.assertEqual(self.n.db.execute("select last_tick from rr_stream_promotions where stream_id='s1'").fetchone()[0], 1)
        self.assertIsNone(self.n.follow_tick("s1", self.now+timedelta(minutes=21), live=True))
        self.assertEqual(self.n.follow_tick("s1", self.now+timedelta(minutes=40), live=True), FOLLOW_BANK[1])

    def test_retention_purges_controls_processed_dedup_and_stale_alarms(self):
        self.n.owner_id="999"
        self.n.handle_control("!rr remind 1m later", "999", "s", "control1", self.now)
        # A due item that never delivered cannot stay forever.
        self.n.add_reminder_at("999", "s", self.now-timedelta(days=31), "stale", self.now-timedelta(days=32))
        with self.n.db:
            self.n.db.execute("INSERT INTO rr_processed_automation_messages VALUES('s','msg-old',?)", ((self.now-timedelta(days=31)).isoformat(),))
            self.n.db.execute("INSERT INTO rr_first_chat_seen VALUES('s','123','first-old','old',?)", ((self.now-timedelta(days=31)).isoformat(),))
            self.n.db.execute("INSERT INTO rr_automation_controls VALUES('ctl-old','999','ok',?)", ((self.now-timedelta(days=31)).isoformat(),))
        self.n.purge_retained(self.now)
        self.assertEqual(self.n.db.execute("SELECT message FROM rr_reminders").fetchall(), [("later",)])
        for table in ("rr_processed_automation_messages", "rr_first_chat_seen"):
            self.assertEqual(self.n.db.execute("SELECT count(*) FROM " + table).fetchone()[0], 0, table)
        self.assertEqual(self.n.db.execute("SELECT count(*) FROM rr_automation_controls WHERE message_id='ctl-old'").fetchone()[0], 0)
        self.assertEqual(self.n.db.execute("SELECT count(*) FROM rr_automation_controls WHERE message_id='control1'").fetchone()[0], 1)

    def test_rule_phrase_parser(self):
        parsed=parse_automation_control("Whenever you hear the word phone, say knock knock")
        self.assertEqual((parsed["phrase"],parsed["response"]),("phone","knock knock"))
        explicit=parse_automation_control("!rr rule add phone when phone => knock knock")
        self.assertEqual(explicit["name"],"phone")
        self.assertEqual(parse_automation_control("whenever a viewer says phone, give them admin"),None)

    def test_first_chat_immutable_identity_and_stream_scope(self):
        self.assertTrue(self.n.first_chat("s1","123","viewer","m1",self.now))
        self.assertFalse(self.n.first_chat("s1","123","viewer","m2",self.now))
        self.assertTrue(self.n.first_chat("s2","123","viewer","m3",self.now))
        self.assertFalse(self.n.first_chat("s1","viewer","viewer","m4",self.now))

    def test_follow_timer_deduplicates_skips_missed_ticks_and_guardrails(self):
        self.n.start_stream("s1",self.now)
        self.assertIsNone(self.n.follow_tick("s1",self.now+timedelta(minutes=19),live=True))
        self.assertIsNone(self.n.follow_tick("s1",self.now+timedelta(minutes=20),live=True,muted=True))
        self.assertEqual(self.n.db.execute("select last_tick from rr_stream_promotions").fetchone()[0],1)
        self.assertEqual(self.n.follow_tick("s1",self.now+timedelta(minutes=40),live=True),FOLLOW_BANK[1])
        # A reconnect during a long delay emits only the latest due tick once.
        message=self.n.follow_tick("s1",self.now+timedelta(hours=5),live=True)
        self.assertIsNotNone(message)
        self.assertIsNone(self.n.follow_tick("s1",self.now+timedelta(hours=5),live=True))
        self.assertGreaterEqual(len(FOLLOW_BANK),20)
        self.n.end_stream("s1",self.now+timedelta(hours=5))
        self.assertIsNone(self.n.follow_tick("s1",self.now+timedelta(hours=6),live=True))

if __name__=="__main__":unittest.main()
