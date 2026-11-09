import sqlite3
import unittest
from datetime import datetime,timezone,timedelta
from mario import Mario

class MarioTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.game=Mario(self.db)
        self.game.enable("stream1")
        self.game.roster("stream1",["raf","moodbasket","joey"])
    def tearDown(self):self.db.close()

    def test_independent_confirmations(self):
        self.assertIn("1 more independent",self.game.vote("stream1","v1","raff"))
        self.assertEqual(self.game.vote("stream1","v1","raf"),"vote already recorded for this round")
        self.assertIn("first place: raf",self.game.vote("stream1","v2","raf"))
        self.assertEqual(self.game.scores("stream1"),[("raf",1)])
        self.assertIn("already recorded",self.game.vote("stream1","v3","moodbasket"))

    def test_roster_update_and_ambiguous_alias(self):
        self.assertIsNone(self.game.resolve("stream1","someoneelse"))
        self.assertEqual(self.game.resolve("stream1","moodbaskt"),"moodbasket")
        with self.assertRaises(ValueError):self.game.roster("stream1",["raf","raf"])

    def test_next_round_and_history(self):
        self.assertIn("confirm",self.game.next_round("stream1"))
        self.game.vote("stream1","operator","raf",operator=True)
        self.assertIn("round 2",self.game.next_round("stream1"))
        self.game.vote("stream1","operator","joey",operator=True)
        self.assertEqual(self.game.scores(),[("joey",1),("raf",1)])
        self.assertEqual(self.game.scores("stream1"),[("joey",1),("raf",1)])

    def test_reset_is_session_scoped_and_disables_mode(self):
        self.game.vote("stream1","operator","joey",operator=True)
        self.game.enable("otherstream")
        self.game.roster("otherstream",["ali","joey"])
        self.assertIn("reset",self.game.reset("stream1"))
        self.assertEqual(self.game.status("stream1"),("off",1,0))
        self.assertEqual(self.game.scores("stream1"),[])
        self.assertEqual(self.game.db.execute("SELECT count(*) FROM mario_votes WHERE stream_id='stream1'").fetchone()[0],0)
        self.assertTrue(self.game.active("otherstream"))

    def test_expires_automatically_after_five_hours(self):
        old=(datetime.now(timezone.utc)-timedelta(hours=6)).isoformat()
        self.db.execute("UPDATE mario_sessions SET enabled_utc=? WHERE stream_id='stream1'",(old,))
        self.db.commit()
        self.assertFalse(self.game.active("stream1"))
        self.assertEqual(self.game.status("stream1")[0],"off")

    def test_migrates_older_sessions_without_timestamp(self):
        db=sqlite3.connect(":memory:")
        try:
            db.execute("CREATE TABLE mario_sessions(stream_id TEXT PRIMARY KEY,enabled INTEGER NOT NULL DEFAULT 0,current_round INTEGER NOT NULL DEFAULT 1)")
            db.execute("INSERT INTO mario_sessions VALUES('oldstream',1,1)")
            old=Mario(db)
            self.assertFalse(old.active("oldstream"))  # unknown age never remains on forever
            old.enable("oldstream")
            self.assertTrue(old.active("oldstream"))
        finally:db.close()

    def test_mode_toggle(self):
        self.game.enable("stream1",False)
        self.assertEqual(self.game.vote("stream1","v1","raf"),"mario kart mode is off")
        self.assertFalse(self.game.active("stream1"))

if __name__=="__main__":unittest.main()
