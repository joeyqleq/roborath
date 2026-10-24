import sqlite3
import unittest
from datetime import datetime, timezone, timedelta
from policy import PolicyStore, parse_public

class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:", isolation_level=None)
        self.policy=PolicyStore(self.db, owner_id="12345", broadcaster_id="99999")
    def tearDown(self):self.db.close()

    def test_invocation_is_explicit(self):
        for text in ["rath said hello", "RoboRath you there", "cheer100", "!factoid false"]:
            self.assertIsNone(parse_public(text))
        self.assertEqual(parse_public("!fact hello"), ("fact","hello"))
        self.assertEqual(parse_public("hey RoboRath, research this") , ("research","this"))
        self.assertEqual(parse_public("@RoboRath fact hello"), ("fact","hello"))

    def test_fact_quota_and_stream_reset(self):
        for i in range(2):
            self.assertTrue(self.policy.check_or_reserve("444",f"m{i}","fact","stream1").allowed)
        self.assertFalse(self.policy.check_or_reserve("444","m3","fact","stream1").allowed)
        self.assertTrue(self.policy.check_or_reserve("444","m4","fact","stream2").allowed)

    def test_research_quota_daily(self):
        self.assertTrue(self.policy.check_or_reserve("444","r1","research","stream1","2026-10-24").allowed)
        self.assertFalse(self.policy.check_or_reserve("444","r2","research","stream2","2026-10-24").allowed)
        self.assertTrue(self.policy.check_or_reserve("444","r3","research","stream2","2026-10-25").allowed)

    def test_owner_and_broadcaster_unlimited(self):
        for i in range(4):
            self.assertTrue(self.policy.check_or_reserve("12345",f"o{i}","fact","stream1").allowed)
            self.assertTrue(self.policy.check_or_reserve("99999",f"s{i}","research","stream1").allowed)

    def test_no_username_privilege(self):
        with self.assertRaises(ValueError):PolicyStore(self.db,"joeyleq","rath_bone")
        self.assertFalse(self.policy.check_or_reserve("joeyleq","x1","fact","s").reason=="owner/broadcaster unlimited")
        with self.assertRaises(PermissionError):
            self.policy.delegate("joeyleq","444","fact_grant",True)
        with self.assertRaises(PermissionError):
            self.policy.grant_extra("444","555","fact", "stream:stream1",2)

    def test_bounded_delegation_revocation(self):
        self.policy.delegate("12345","444","fact_grant",True)
        self.assertTrue(self.policy.can_manage("444","fact_grant"))
        self.assertFalse(self.policy.can_manage("444","research_grant"))
        self.policy.grant_extra("444","555","fact","stream:stream1",2)
        for i in range(4):
            self.assertTrue(self.policy.check_or_reserve("555",f"q{i}","fact","stream1").allowed)
        self.assertFalse(self.policy.check_or_reserve("555","q5","fact","stream1").allowed)
        self.policy.delegate("12345","444","fact_grant",False)
        with self.assertRaises(PermissionError):
            self.policy.grant_extra("444","555","fact","stream:stream1",1)

    def test_idempotence_refund(self):
        self.assertTrue(self.policy.check_or_reserve("444","repeat","fact","s").allowed)
        self.assertFalse(self.policy.check_or_reserve("444","repeat","fact","s").allowed)
        self.policy.refund("repeat")
        self.assertTrue(self.policy.check_or_reserve("444","repeat","fact","s").allowed)

    def test_delete_permissions(self):
        self.policy.delegate("12345","444","research_grant",True)
        self.policy.grant_extra("12345","444","research","day:2026-10-24",4)
        self.policy.check_or_reserve("444","d1","research","s","2026-10-24")
        self.policy.forget("444")
        self.assertFalse(self.policy.can_manage("444","research_grant"))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM rr_consumptions").fetchone()[0],0)

if __name__=="__main__":
    unittest.main()
