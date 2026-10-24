import unittest
from formatting import compress_for_chat,utf8_clip,humanize,messages,URL

class FormatTests(unittest.TestCase):
    def test_utf8_byte_budget(self):
        s=utf8_clip("🇱🇧"*200,420)
        self.assertLessEqual(len(s.encode("utf-8")),420)
        self.assertTrue(s.endswith("..."))
    def test_one_fact_one_message(self):
        answer="This claim needs context. "*90
        result=messages(answer,"fact")
        self.assertEqual(len(result),1)
        self.assertLessEqual(len(result[0].encode()),420)
    def test_research_at_most_two(self):
        for size in (1,500,5000):
            msgs=messages("a"*size,"research")
            self.assertLessEqual(len(msgs),2)
            self.assertTrue(all(len(m.encode())<=420 for m in msgs))
    def test_no_raw_url(self):
        txt='read https://example.com/path?q=long'
        self.assertNotIn("https://",messages(txt,"fact")[0])
    def test_json_human_readable(self):
        self.assertEqual(humanize('{"answer": "yes", "verdict": "confirmed"}'),"yes. confirmed")
    def test_no_empty(self):
        self.assertTrue(messages("","fact")[0])
if __name__=='__main__': unittest.main()
