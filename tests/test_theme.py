import sqlite3
import unittest
from theme import StreamTheme


class ThemeTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.t=StreamTheme(self.db);self.t.activate()
    def tearDown(self):self.db.close()
    def test_exactly_three_verified_streams_with_restart_dedupe(self):
        self.assertFalse(self.t.observe('uncertain-x',True))
        self.assertFalse(self.t.observe('first',False))
        self.assertTrue(self.t.observe('first',True))
        self.assertTrue(StreamTheme(self.db).observe('first',True))
        self.assertTrue(self.t.observe('second',True))
        self.assertTrue(self.t.observe('third',True))
        self.assertFalse(self.t.observe('fourth',True))
        self.assertFalse(self.t.active('fourth'))
    def test_topic_relevance_and_honest_pending_status(self):
        self.t.observe('one',True)
        self.assertEqual(self.t.context('one','what is a bicycle'), '')
        self.assertIn('do not claim impeachment passed',self.t.context('one','Massie and Hegseth'))
        self.assertEqual(self.t.context('other','Hegseth'), '')
    def test_capped_posts_and_stop(self):
        self.t.observe('one',True)
        first=self.t.reserve_post('one',100)
        self.assertIsNotNone(first)
        self.assertIsNone(self.t.reserve_post('one',101))
        second=self.t.reserve_post('one',2800)
        third=self.t.reserve_post('one',5500)
        self.assertEqual(len({first,second,third}),3)
        self.assertIsNone(self.t.reserve_post('one',9000))
        self.t.stop()
        self.assertFalse(self.t.active('one'))
