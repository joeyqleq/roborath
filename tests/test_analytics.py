import sqlite3
import unittest
from datetime import datetime, timezone, timedelta
from analytics import initialize,record,remove_user,regulars,prune

class AnalyticsTest(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        initialize(self.db)
        self.now=datetime(2026,10,24,12,0,tzinfo=timezone.utc)

    def test_regular_activity_no_psych_inference(self):
        for day in range(3):
            for b in range(12):
                timestamp=self.now-timedelta(days=day,minutes=5*b)
                record(self.db,"user-123","regular","stream-"+str(day),timestamp)
        record(self.db,"user-456","visitor","stream-0",self.now)
        rows=regulars(self.db,now=self.now)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0][0],"user-123")
        self.assertEqual(rows[0][3],36)
        self.assertEqual(rows[0][5],3)

    def test_counts_and_deletion(self):
        record(self.db,"u","viewer","stream",self.now)
        record(self.db,"u","viewer","stream",self.now)
        self.assertEqual(self.db.execute("SELECT message_count FROM activity_buckets").fetchone()[0],2)
        remove_user(self.db,"u")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM activity_buckets").fetchone()[0],0)

    def test_prune(self):
        record(self.db,"old","viewer","s",self.now-timedelta(days=190))
        record(self.db,"new","viewer","s",self.now)
        prune(self.db,now=self.now)
        self.assertEqual(self.db.execute("SELECT twitch_user_id FROM activity_buckets").fetchall(),[("new",)])

if __name__=='__main__':
    unittest.main()
