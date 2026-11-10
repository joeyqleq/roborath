import sqlite3
import unittest
from policy import OWNER_TWITCH_ID, PolicyStore, parse_public


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.policy = PolicyStore(self.db, OWNER_TWITCH_ID, "99999")

    def tearDown(self):
        self.db.close()

    def test_parser_is_explicit_and_unifies_verification(self):
        for text in ("rath said hello", "RoboRath you there", "cheer100", "!factoid false"):
            self.assertIsNone(parse_public(text))
        for text in ("!fact hello", "!check hello", "!verify hello", "@RoboRath verify hello"):
            self.assertEqual(parse_public(text), ("fact", "hello"))
        self.assertEqual(parse_public("!verify deep why seasons happen"), ("research", "why seasons happen"))
        self.assertEqual(parse_public("!check research history of Mao"), ("research", "history of Mao"))
        self.assertEqual(parse_public("hey RoboRath, research this"), ("research", "this"))

    def test_fact_quota_and_stream_reset(self):
        self.assertTrue(self.policy.check_or_reserve("444", "m0", "fact", "stream1").allowed)
        self.assertFalse(self.policy.check_or_reserve("444", "m3", "fact", "stream1").allowed)
        self.assertTrue(self.policy.check_or_reserve("444", "m4", "fact", "stream2").allowed)

    def test_research_quota_daily(self):
        self.assertTrue(self.policy.check_or_reserve("444", "r1", "research", "stream1", "2026-10-24").allowed)
        self.assertFalse(self.policy.check_or_reserve("444", "r2", "research", "stream2", "2026-10-24").allowed)
        self.assertTrue(self.policy.check_or_reserve("444", "r3", "research", "stream2", "2026-10-25").allowed)

    def test_owner_and_broadcaster_unlimited(self):
        for i in range(4):
            self.assertTrue(self.policy.check_or_reserve(OWNER_TWITCH_ID, f"o{i}", "fact", "stream1").allowed)
            self.assertTrue(self.policy.check_or_reserve("99999", f"s{i}", "research", "stream1").allowed)

    def test_owner_identity_is_pinned_and_usernames_are_not_privileged(self):
        with self.assertRaises(ValueError):
            PolicyStore(self.db, "12345", "99999")
        with self.assertRaises(ValueError):
            PolicyStore(self.db, "joeyleq", "rath_bone")
        self.assertFalse(self.policy.check_or_reserve("joeyleq", "x1", "fact", "s").reason == "owner/broadcaster unlimited")

    def test_only_owner_can_allocate_extra_quota_or_manage(self):
        with self.assertRaises(PermissionError):
            self.policy.grant_extra("444", "555", "fact", "stream:stream1", 2)
        with self.assertRaises(ValueError):
            self.policy.delegate(OWNER_TWITCH_ID, "444", "fact_grant", True)
        self.assertFalse(self.policy.can_manage("444", "mario_manage"))
        self.assertTrue(self.policy.can_manage(OWNER_TWITCH_ID, "mario_manage"))
        self.policy.grant_extra(OWNER_TWITCH_ID, "555", "fact", "stream:stream1", 2)
        for i in range(3):
            self.assertTrue(self.policy.check_or_reserve("555", f"q{i}", "fact", "stream1").allowed)
        self.assertFalse(self.policy.check_or_reserve("555", "q5", "fact", "stream1").allowed)

    def test_idempotence_refund_and_forget(self):
        self.assertTrue(self.policy.check_or_reserve("444", "repeat", "fact", "s").allowed)
        self.assertFalse(self.policy.check_or_reserve("444", "repeat", "fact", "s").allowed)
        self.policy.refund("repeat")
        self.assertTrue(self.policy.check_or_reserve("444", "repeat", "fact", "s").allowed)
        self.policy.forget("444")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM rr_consumptions").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
