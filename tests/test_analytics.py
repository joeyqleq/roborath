import sqlite3
import unittest
from datetime import datetime, timezone, timedelta
from analytics import initialize, record, record_reply, remove_user, regulars, prune, DEFAULT_RETENTION_DAYS


class AnalyticsTest(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        initialize(self.db)
        self.now=datetime(2026,10,24,12,0,tzinfo=timezone.utc)

    def tearDown(self): self.db.close()

    def test_daily_counts_messages_words_and_replies(self):
        record(self.db,"123","regular","stream",self.now,"m1","hello, wonderful chat")
        record(self.db,"123","regular","stream",self.now+timedelta(hours=1),"m2","one more line",is_reply=True)
        record_reply(self.db,"123","reply-1","Thanks for that thoughtful question",self.now+timedelta(hours=2),"stream","regular")
        row=self.db.execute("SELECT bucket_start_utc,message_count,word_count,reply_count,native_reply_count,bot_reply_count FROM activity_buckets").fetchone()
        self.assertEqual(row[0],"2026-10-24")
        self.assertEqual(row[1:],(2,6,2,1,1))

    def test_message_and_reply_ids_make_replays_idempotent(self):
        self.assertTrue(record(self.db,"u","viewer","s",self.now,"m1","hello world"))
        self.assertFalse(record(self.db,"u","viewer","s",self.now,"m1","hello world"))
        self.assertTrue(record_reply(self.db,"u","r1","hi",self.now,"s"))
        self.assertFalse(record_reply(self.db,"u","r1","hi",self.now,"s"))
        row=self.db.execute("SELECT message_count,word_count,reply_count,native_reply_count,bot_reply_count FROM activity_buckets").fetchone()
        self.assertEqual(row,(1,2,1,0,1))

    def test_reply_content_metrics_exclude_recipient(self):
        record(self.db,'u','alice','s',self.now,'reply','bob, Hello world!',is_reply=True,reply_login='bob')
        self.assertEqual(self.db.execute('SELECT word_count,character_count FROM activity_buckets').fetchone(),(2,11))

    def test_regular_aggregates_daily_counts_no_psych_inference(self):
        for day in range(3):
            for index in range(12):
                record(self.db,"user-123","regular","stream-"+str(day),self.now-timedelta(days=day,minutes=5*index),f"{day}-{index}","hey chat")
        record(self.db,"user-456","visitor","stream-0",self.now,"solo","hi")
        rows=regulars(self.db,minimum_active_buckets=3,now=self.now)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0][0],"user-123")
        self.assertEqual(rows[0][2],36)
        self.assertEqual(rows[0][3],3)  # one daily row per stream/day
        self.assertEqual(rows[0][5],3)
        self.assertEqual(rows[0][6],72)
        self.assertEqual(rows[0][7],0)  # legacy combined count
        self.assertEqual(rows[0][8],0)  # native Twitch replies
        self.assertEqual(rows[0][9],0)  # RoboRath replies

    def test_legacy_five_minute_aggregates_migrate_to_daily(self):
        old=sqlite3.connect(":memory:")
        old.execute("""CREATE TABLE activity_buckets(twitch_user_id TEXT NOT NULL,twitch_login TEXT NOT NULL,stream_id TEXT NOT NULL,bucket_start_utc TEXT NOT NULL,message_count INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(twitch_user_id,stream_id,bucket_start_utc))""")
        old.execute("INSERT INTO activity_buckets VALUES('u','viewer','s','2026-10-24T12:00:00+00:00',2)")
        old.execute("INSERT INTO activity_buckets VALUES('u','viewer','s','2026-10-24T12:05:00+00:00',3)")
        initialize(old)
        self.assertEqual(old.execute("SELECT bucket_start_utc,message_count,word_count,reply_count FROM activity_buckets").fetchall(),[("2026-10-24",5,0,0)])
        initialize(old)
        self.assertEqual(old.execute("SELECT message_count,native_reply_count,bot_reply_count FROM activity_buckets").fetchone(),(5,0,0))
        # Upgrade from the prior v2 schema, retaining its legacy combined count.
        old.execute("ALTER TABLE activity_buckets DROP COLUMN native_reply_count")
        old.execute("ALTER TABLE activity_buckets DROP COLUMN bot_reply_count")
        initialize(old)
        self.assertEqual(old.execute("SELECT reply_count,native_reply_count,bot_reply_count FROM activity_buckets").fetchone(),(0,0,0))
        self.assertEqual(old.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name='activity_recent'").fetchone()[0],1)
        old.close()

    def test_thirty_day_prune_covers_counts_and_idempotency_keys(self):
        self.assertEqual(DEFAULT_RETENTION_DAYS,30)
        record(self.db,"old","viewer","s",self.now-timedelta(days=30),"old-message","private text not stored")
        record_reply(self.db,"old","old-reply","reply",self.now-timedelta(days=30),"s")
        record(self.db,"new","viewer","s",self.now,"new-message","hi")
        prune(self.db,now=self.now)
        self.assertEqual(self.db.execute("SELECT twitch_user_id FROM activity_buckets").fetchall(),[("new",)])
        self.assertEqual(self.db.execute("SELECT message_id FROM activity_message_ids").fetchall(),[("new-message",)])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM activity_reply_ids").fetchone()[0],0)

    def test_deletion_removes_counts_and_dedupe_state(self):
        record(self.db,"u","viewer","s",self.now,"m","hi")
        record_reply(self.db,"u","r","hello",self.now,"s")
        remove_user(self.db,"u")
        for table in ("activity_buckets","activity_message_ids","activity_reply_ids"):
            self.assertEqual(self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],0)

    def test_timezone_and_missing_identifiers(self):
        with self.assertRaises(ValueError): record(self.db,"u","v","s",datetime(2026,10,24),"m","hi")
        self.assertFalse(record(self.db,"u","v","",self.now,"m","hi"))
        self.assertFalse(record_reply(self.db,"u","","hi",self.now,"s"))

if __name__=='__main__': unittest.main()
