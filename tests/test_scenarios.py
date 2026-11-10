import unittest
from scenarios import (classify,exact_letter_count,history_context,
                       repeated_count_correction,resolve_search_query,
                       is_search_followup)


class ScenarioTests(unittest.TestCase):
    def test_letter_counts_all_log_variants(self):
        for phrasing in (
            "how many r’s are there in strawberry?",
            "how many r’s r there in strawberry?",
            "how many r’s r there in sstrawberry?",
            "how many r's are their in strawberry?",
            "how many r's r there in strawberry?"):
            with self.subTest(phrasing=phrasing):
                self.assertIn("3 occurrences",exact_letter_count(phrasing))
                self.assertEqual(classify(phrasing).kind,"letter_count")
        self.assertIn("4 occurrences",exact_letter_count("how many s are in mississippi?"))

    def test_routing_scenarios(self):
        prior="!search what is the latest video for rabbi shmuley called? from his accounts only."
        cases=[
            ("!search what is the latest video for rabbi shmuley called?","official_video"),
            ("what is the latest video for Rabbi Shmuley called?","official_video"),
            ("tell me the title name","official_video"),
            ("what is the previous answer?","memory_followup"),
            ("analyze your last 3 responses, where is the anomaly?","memory_followup"),
            ("are you sure? u get another try.","memory_followup"),
            ("is the strawberry question still in your memory?","memory_followup"),
            ("what do you know about Mario Kart?","general"),
            ("hi","general"),
        ]
        for q,expected in cases:
            with self.subTest(q=q):
                self.assertEqual(classify(q,previous_search=prior).kind,expected)
        self.assertEqual(classify("tell me the title name").kind,"ambiguous_title")
        self.assertEqual(classify("search for routers",explicit_search=True).kind,"web_search")

    def test_viewer_scoped_history_and_old_answer_correction(self):
        rows=[
            ("!ask how many r's are there in strawberry?","Six.","chat"),
            ("!ask how many r's are there in strawberry?","'strawberry' contains 3 occurrences of 'r'.","chat"),
            ("!search latest video","some search results","search"),
        ]
        correction=repeated_count_correction("analyze your last 3 responses",rows)
        self.assertIn("6 answer was wrong",correction)
        self.assertIn("3 occurrences",correction)
        history=history_context(rows)
        self.assertIn("!search latest video",history)
        self.assertIn("Six.",history)
        self.assertIn("may contain errors",history)

    def test_generic_search_followup_uses_prior_viewer_question_not_bot_answer(self):
        rows = [
            ("!ask Who is the public business figure named Pat Example?",
             "There is no evidence they own any businesses.", "chat"),
            ("!ask Earlier unrelated question", "An unrelated answer", "chat"),
        ]
        self.assertTrue(is_search_followup("search the web"))
        self.assertEqual(resolve_search_query("search the web", rows),
                         "Who is the public business figure named Pat Example?")
        self.assertEqual(resolve_search_query("incorrect. search the web", rows),
                         "Who is the public business figure named Pat Example?")
        self.assertEqual(resolve_search_query("look it up", rows),
                         "Who is the public business figure named Pat Example?")
        self.assertEqual(resolve_search_query("search and you shall find", rows),
                         "Who is the public business figure named Pat Example?")
        self.assertEqual(resolve_search_query("search nd you shall find", rows),
                         "Who is the public business figure named Pat Example?")

    def test_topical_search_followup_keeps_current_subject(self):
        rows = [("!ask old question", "old answer", "chat")]
        for phrase in ("search for latest Formula 1 standings",
                       "!search latest Formula 1 standings"):
            with self.subTest(phrase=phrase):
                self.assertIsNone(resolve_search_query(phrase, rows))

    def test_search_followup_skips_prior_search_command_and_non_substantive_rows(self):
        rows = [
            ("search the web", "Search lead output", "search"),
            ("!ask", "Usage example", "chat"),
            ("!ask Why did the Berlin Wall fall?", "Unsupported confident answer", "chat"),
        ]
        self.assertEqual(resolve_search_query("look it up", rows),
                         "Why did the Berlin Wall fall?")


if __name__=="__main__":
    unittest.main()
