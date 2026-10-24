import sqlite3
import unittest
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

    def test_mode_toggle(self):
        self.game.enable("stream1",False)
        self.assertEqual(self.game.vote("stream1","v1","raf"),"mario kart mode is off")
        self.assertFalse(self.game.active("stream1"))

if __name__=="__main__":unittest.main()
