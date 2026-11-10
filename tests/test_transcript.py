import sqlite3
import unittest
from datetime import datetime, timedelta, timezone

from transcript import TranscriptStore


class TranscriptStoreTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.store = TranscriptStore(self.db)
        self.base = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)

    def tearDown(self):
        self.db.close()

    def add(self, sid, mid, uid, text, minutes=0, login=None):
        when = self.base + timedelta(minutes=minutes)
        return self.store.record(sid, mid, uid, login or uid, text, when)

    def test_deduplicates_global_twitch_id_and_keeps_timestamps_utc(self):
        self.assertTrue(self.add("stream-a", "message-1", "u1", "one", login="VIEWER"))
        self.assertFalse(self.add("stream-b", "message-1", "u1", "replayed"))
        result = self.store.recent_context("stream-a", self.base - timedelta(minutes=1))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["login"], "viewer")
        self.assertEqual(result[0]["created_utc"], "2026-11-10T12:00:00.000000+00:00")
        self.assertFalse(self.store.coverage("stream-a")["complete"])

    def test_shared_5h_context_and_three_hour_search_is_stream_scoped(self):
        for i in range(1000):
            self.add("s1", f"m{i}", f"u{i % 7}",
                     "Mao debate about the red book" if i == 400 else f"ordinary chat item {i}",
                     minutes=180 if i == 400 else i * 0.25)
        self.add("s2", "other", "u0", "Mao debate about the red book", minutes=600)
        query_time = self.base + timedelta(minutes=180)
        hits = self.store.search("s1", "Mao debate", start_utc=query_time - timedelta(minutes=1),
                                 end_utc=query_time + timedelta(minutes=1))
        self.assertEqual([x["message_id"] for x in hits], ["m400"])
        self.assertEqual(self.store.search("s1", "Mao debate", twitch_user_id="u2"), [])
        context = self.store.recent_context("s1", self.base, limit=1000)
        self.assertEqual(len(context), 100)
        self.assertTrue(all(row["message_id"] != "other" for row in context))
        self.assertEqual(self.store.coverage("s1")["message_count"], 1000)

    def test_optout_deletes_messages_fts_and_summaries_but_not_other_users(self):
        self.add("s", "a", "u1", "the secret Mao claim")
        self.add("s", "b", "u2", "public follow-up")
        self.assertTrue(self.store.store_summary("s", self.base, self.base + timedelta(minutes=1),
                                                 "Summary with sources", ["a", "b"]))
        self.assertEqual(self.store.opt_out("u1"), 1)
        self.assertTrue(self.store.is_opted_out("u1"))
        self.assertFalse(self.add("s", "c", "u1", "not archived"))
        self.assertEqual(self.store.search("s", "secret"), [])
        self.assertEqual(self.store.search("s", "follow-up")[0]["message_id"], "b")
        self.assertEqual(self.store.summaries("s"), [])
        self.store.opt_in("u1")
        self.assertTrue(self.add("s", "d", "u1", "new chat"))
        self.assertEqual(self.store.search("s", "secret"), [])

    def test_moderation_user_delete_returns_streams_and_invalidates_all_derived_summaries(self):
        self.add("s1", "a", "u1", "old source", minutes=0)
        self.add("s1", "b", "u2", "other source", minutes=1)
        self.add("s2", "c", "u1", "second stream source", minutes=2)
        self.assertTrue(self.store.store_summary("s1", self.base, self.base + timedelta(minutes=1), "derived", ["a", "b"]))
        self.assertTrue(self.store.store_summary("s2", self.base + timedelta(minutes=2), self.base + timedelta(minutes=3), "derived too", ["c"]))
        self.assertEqual(self.store.delete_user("u1"), {"s1", "s2"})
        self.assertFalse(self.store.is_opted_out("u1"))
        self.assertEqual(self.store.search("s1", "old source"), [])
        self.assertEqual(self.store.summaries("s1"), [])
        self.assertEqual(self.store.summaries("s2"), [])
        self.assertEqual(self.store.coverage("s1")["message_count"], 1)

    def test_delete_stream_purges_all_text_gaps_and_metadata(self):
        self.store.observe_stream("s", "broadcaster", self.base)
        self.add("s", "a", "u1", "public text")
        self.store.mark_gap("s", self.base, self.base + timedelta(minutes=1))
        self.assertEqual(self.store.delete_stream("s"), 1)
        self.assertFalse(self.store.coverage("s")["observed"])
        self.assertEqual(self.store.search("s", "public text"), [])

    def test_privacy_commands_work_at_intake_before_eligibility_gates(self):
        self.add("s", "a", "u1", "prior public chat")
        self.assertFalse(self.add("s", "optout", "u1", "!forgetme"))
        self.assertTrue(self.store.is_opted_out("u1"))
        self.assertEqual(self.store.search("s", "prior public"), [])
        self.assertFalse(self.add("s", "blocked", "u1", "still opted out"))
        self.assertFalse(self.add("s", "optin", "u1", "!optin"))
        self.assertTrue(self.add("s", "new", "u1", "new public chat"))

    def test_twitch_deletion_removes_index_and_dependent_summary(self):
        self.add("s", "a", "u1", "first message")
        self.add("s", "b", "u2", "second message")
        self.assertTrue(self.store.store_summary("s", self.base, self.base + timedelta(minutes=1),
                                                 "Combined", ["a", "b"]))
        self.assertEqual(self.store.delete_message("a"), 1)
        self.assertEqual(self.store.delete_message("a"), 0)
        self.assertEqual(self.store.search("s", "first"), [])
        self.assertEqual(self.store.summaries("s"), [])
        self.assertEqual(self.store.coverage("s")["message_count"], 1)

    def test_summary_citations_must_be_valid_stream_and_window_sources(self):
        self.add("s", "a", "u1", "hello", minutes=0)
        self.add("s", "b", "u2", "world", minutes=5)
        self.assertFalse(self.store.store_summary("s", self.base, self.base + timedelta(minutes=1), "bad", ["b"]))
        self.assertFalse(self.store.store_summary("s", self.base, self.base + timedelta(minutes=5), "bad", ["missing"]))
        self.assertTrue(self.store.store_summary("s", self.base, self.base + timedelta(minutes=5), "ok", ["a", "b"]))
        self.assertEqual(self.store.summaries("s")[0]["source_message_ids"], ["a", "b"])

    def test_30_day_purge_removes_fts_summaries_and_empty_stream(self):
        old = self.base - timedelta(days=31)
        self.store.record("old", "old1", "u1", "viewer", "old unique phrase", old)
        self.assertTrue(self.store.store_summary("old", old, old + timedelta(minutes=1), "old summary", ["old1"]))
        self.assertEqual(self.store.purge(self.base), 1)
        self.assertEqual(self.store.search("old", "unique phrase"), [])
        self.assertEqual(self.store.summaries("old"), [])
        self.assertFalse(self.store.coverage("old")["observed"])

    def test_authoritative_stream_metadata_and_capture_gaps_are_reported(self):
        self.store.observe_stream("live-1", "broadcaster-1", self.base - timedelta(minutes=10))
        self.store.mark_gap("live-1", self.base, None, "irc_disconnect")
        self.store.close_gap("live-1", self.base + timedelta(minutes=2))
        coverage = self.store.coverage("live-1")
        self.assertEqual(coverage["broadcaster_id"], "broadcaster-1")
        self.assertEqual(coverage["stream_started_utc"], "2026-11-10T11:50:00.000000+00:00")
        self.assertEqual(coverage["gaps"][0]["reason"], "irc_disconnect")
        self.assertEqual(coverage["gaps"][0]["end_utc"], "2026-11-10T12:02:00.000000+00:00")
        self.assertIsNone(coverage["complete"])

    def test_natural_language_query_returns_attributed_excerpts(self):
        self.add("s", "before", "u1", "song discussion starts", minutes=0)
        self.add("s", "first", "u2", "I mentioned the song", minutes=1)
        self.add("s", "target", "viewer3", "I said Mao caused hardship", minutes=180)
        self.add("s", "correction", "u4", "Actually, the date is wrong", minutes=181)
        three_hours_ago = self.base + timedelta(hours=6)
        result = self.store.answer_question("s", "What did user viewer3 say 3 hours ago?", now=three_hours_ago)
        self.assertEqual([x["message_id"] for x in result["excerpts"]], ["target"])
        self.assertEqual(result["excerpts"][0]["login"], "viewer3")
        first = self.store.query_context("s", "Who first mentioned the song?", now=three_hours_ago + timedelta(minutes=1))
        self.assertEqual([x["message_id"] for x in first], ["before"])
        corrections = self.store.query_context("s", "Has anyone corrected that claim?", now=three_hours_ago + timedelta(minutes=2))
        self.assertEqual([x["message_id"] for x in corrections], ["correction"])

    def test_chunked_excerpt_summary_has_sources_and_export_requires_operator(self):
        self.add("s", "a", "u1", "Mao and the red book", minutes=0)
        self.add("s", "b", "u2", "Mao debate continues", minutes=31)
        chunks = self.store.chunked_excerpts("s", self.base, self.base + timedelta(hours=1))
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["source_message_ids"], ["a"])
        with self.assertRaises(PermissionError):
            self.store.export_jsonl("s")
        self.assertIn('"message_id": "a"', self.store.export_jsonl("s", operator_authorized=True))
        self.assertEqual(self.store.export_text("s", operator_authorized=True),
                         "u1: Mao and the red book\nu2: Mao debate continues\n")

    def test_naive_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.record("s", "a", "u1", "viewer", "hello", datetime(2026, 1, 1))


if __name__ == "__main__":
    unittest.main()
