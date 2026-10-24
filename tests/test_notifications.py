import sqlite3
import unittest
from datetime import datetime,timezone,timedelta
from notifications import Notifications,parse_duration

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
    def test_forget_and_limits(self):
        for i in range(5):self.n.add_reminder("u1","s1","1h",str(i),self.now)
        with self.assertRaises(ValueError):
            self.n.add_reminder("u1","s1","1h","over",self.now)
        self.n.watch("u1","s1","mario","alert",self.now)
        self.n.forget("u1")
        self.assertEqual(self.n.db.execute("select count(*) from rr_reminders").fetchone()[0],0)
        self.assertEqual(self.n.db.execute("select count(*) from rr_text_watches").fetchone()[0],0)
if __name__=="__main__":unittest.main()
