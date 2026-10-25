import contextlib
import io
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from admin_cli import connect_readonly,status,regulars,quotas,mario,main


class AdminCLITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.dbfile=Path(self.temp.name)/"metrics.sqlite"
        with sqlite3.connect(self.dbfile) as db:
            db.execute("CREATE TABLE chat_events(message_id TEXT PRIMARY KEY)")
            db.execute("INSERT INTO chat_events VALUES ('m1')")
            db.execute("""CREATE TABLE activity_buckets(
             twitch_user_id TEXT,twitch_login TEXT,stream_id TEXT,
             bucket_start_utc TEXT,message_count INTEGER)""")
            db.execute("""INSERT INTO activity_buckets VALUES
               ('42','raf','s1','2026-10-24T12:00:00+00:00',12)""")
            db.execute("""CREATE TABLE rr_consumptions(
               twitch_user_id TEXT,capability TEXT,scope TEXT,used_utc TEXT)""")
            db.execute("""INSERT INTO rr_consumptions VALUES
               ('42','fact','stream:s1','2026-10-24T12:00:00+00:00')""")
            db.execute("CREATE TABLE mario_winners(player TEXT)")
            db.execute("INSERT INTO mario_winners VALUES ('raf')")
            db.commit()
    def tearDown(self):self.temp.cleanup()

    def capture(self,argv):
        buf=io.StringIO()
        with contextlib.redirect_stdout(buf): main(argv)
        return buf.getvalue()

    def test_status_and_regulars(self):
        self.assertIn("received chat messages: 1",
            self.capture(["status","--db",str(self.dbfile)]))
        self.assertIn("raf: 12 msgs",
            self.capture(["regulars","--db",str(self.dbfile)]))

    def test_quotas_and_mario(self):
        self.assertIn("fact 1 used",
            self.capture(["quotas","--db",str(self.dbfile)]))
        self.assertIn("raf: 1 first-place wins",
            self.capture(["mario","--db",str(self.dbfile)]))

    def test_database_is_readonly(self):
        with connect_readonly(str(self.dbfile)) as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("DELETE FROM chat_events")

    def test_bounded_limits(self):
        with self.assertRaises(SystemExit):
            self.capture(["regulars","--db",str(self.dbfile),"--limit","100000"])


if __name__=="__main__":
    unittest.main()
