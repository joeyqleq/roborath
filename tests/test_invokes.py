import sqlite3
import unittest
from invokes import InvokeStore, parse


class InvokeParserTests(unittest.TestCase):
    def test_allowance_phrasings_and_wrappers(self):
        cases = {
            "allow joey": ("allow", ("joey",), None),
            "!ask give @alice 3 invokes": ("set", ("alice",), 3),
            "!rr ask allow alice and bob to invoke your commands": ("allow", ("alice", "bob"), None),
            "grant everyone 2 invokes": ("set", ("*",), 2),
            "global allow": ("global_allow", (), None),
            "global turn off": ("global_off", (), None),
            "take away @alice access": ("deny", ("alice",), None),
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                intent = parse(raw)
                self.assertIsNotNone(intent)
                self.assertEqual((intent.action, intent.targets, intent.amount), expected)

    def test_ambiguous_or_unsafe_phrases_are_not_controls(self):
        for raw in ("allow me to tell you a story", "how many invokes do I have?", "everyone can invoke commands"):
            self.assertIsNone(parse(raw))


class InvokeStoreTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.store = InvokeStore(self.db, "1414798445", "98765")

    def tearDown(self):
        self.db.close()

    def apply(self, mid, targets, action, amount=None):
        return self.store.apply("1414798445", mid, targets, action, amount, "stream-A")

    def test_owner_only_audited_idempotent_apply_and_set_vs_add(self):
        with self.assertRaises(PermissionError):
            self.store.apply("123", "bad", ("456",), "allow")
        self.assertTrue(self.apply("a1", ("456",), "set", 2))
        self.assertFalse(self.apply("a1", ("456",), "set", 2))
        self.assertTrue(self.apply("a2", ("456",), "add", 3))
        self.assertEqual(self.store.limit("456", "stream-A"), 5)

    def test_shared_allowance_atomic_reserve_and_refund(self):
        self.apply("set", ("456",), "set", 2)
        self.assertTrue(self.store.reserve("456", "m1", "stream-A"))
        self.assertTrue(self.store.reserve("456", "m2", "stream-A"))
        self.assertFalse(self.store.reserve("456", "m3", "stream-A"))
        self.store.refund("m1")
        self.assertTrue(self.store.reserve("456", "m4", "stream-A"))
        self.assertEqual(self.store.status("stream-A")["usage"], [("stream-A", "456", 2)])

    def test_global_allow_deny_precedence_and_owner_streamer_rules(self):
        self.apply("wild", ("*",), "set", 2)
        self.assertTrue(self.store.reserve("456", "m1", "s",))
        self.apply("deny", ("456",), "deny")
        self.assertFalse(self.store.reserve("456", "m2", "s"))
        self.apply("off", (), "global_off")
        self.assertFalse(self.store.reserve("98765", "m3", "s"))
        self.assertTrue(self.store.reserve("1414798445", "m4", "s"))
        self.apply("on", (), "global_allow")
        self.assertFalse(self.store.reserve("456", "m5", "s"))  # explicit deny remains

    def test_stream_scoped_allowance_isolated(self):
        self.apply("set", ("456",), "set", 1)
        self.assertTrue(self.store.reserve("456", "m1", "stream-A"))
        self.assertTrue(self.store.reserve("456", "m2", "stream-B"))
        # The numeric budget applies only to the stream in the owner command;
        # future streams fall back to legacy capability-specific quotas.
        self.assertIsNone(self.store.limit("456", "stream-B"))

    def test_unlimited_allow_and_global_allow(self):
        self.apply("allow", ("456",), "allow")
        self.assertEqual(self.store.limit("456", "s"), -1)
        self.assertTrue(self.store.reserve("456", "a", "s"))
        self.apply("off", (), "global_off")
        self.apply("on", (), "global_allow")
        self.assertTrue(self.store.reserve("789", "b", "s"))

    def test_subtract_and_forget(self):
        self.apply("set", ("456",), "set", 5)
        self.apply("sub", ("456",), "subtract", 2)
        self.assertEqual(self.store.limit("456", "stream-A"), 3)
        self.assertTrue(self.store.reserve("456", "a", "stream-A"))
        self.store.forget("456")
        self.assertEqual(self.store.status("stream-A")["usage"], [])


if __name__ == "__main__":
    unittest.main()
