import unittest
from formatting import (UnsafeModelOutput, compress_for_chat, utf8_clip,
                        humanize, messages, URL, validate_final_output)

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
    def test_internal_markers_fail_closed(self):
        for body in (
            '<think>{"name":"search_tools","arguments":{"query":"x"}}</tool_call>',
            '{"role":"tool","content":"source results"}',
            '{"name":"browser","arguments":{"url":"https://example.test"}}',
            '{"nested":[{"name":"lookup","arguments":{"q":"x"}}]}',
            '```json\n{"name":"search_tools","arguments":{}}\n```',
            '<tool_call>search(query="x")</tool_call>',
            '<|tool_call|>{"name":"browser","arguments":{}}<|/tool_call|>',
            '{name:browser,arguments:{url:"https://example.test"}}',
            'partial <think>reasoning with no closing tag',
        ):
            with self.assertRaises(UnsafeModelOutput):
                validate_final_output(body)
            with self.assertRaises(UnsafeModelOutput):
                messages(body,"fact")
    def test_plain_json_and_code_discussion_remain_valid(self):
        self.assertEqual(validate_final_output('{"answer":"yes"}'),'{"answer":"yes"}')
        self.assertEqual(validate_final_output('JSON has a "name" field and an "arguments" field.'),
                         'JSON has a "name" field and an "arguments" field.')
        self.assertIn("JSON",messages("JSON uses keys like name and arguments.","fact")[0])
    def test_successful_short_source_urls_are_preserved(self):
        short = "Answer. https://is.gd/abc123"
        self.assertIn("https://is.gd/abc123", messages(short,"fact")[0])
        research = messages("Long explanation. "*70 + " https://is.gd/abc123", "research")
        self.assertLessEqual(len(research), 2)
        self.assertTrue(any("https://is.gd/abc123" in part for part in research))
    def test_compression_never_changes_substrings(self):
        self.assertEqual(compress_for_chat("young people should go to school"),
                         "young people should go to school")
    def test_unicode_lookalike_protocol_tag_rejected(self):
        with self.assertRaises(UnsafeModelOutput):
            validate_final_output("﹤ｔｈｉｎｋ﹥private reasoning﹤／ｔｈｉｎｋ﹥")
if __name__=='__main__': unittest.main()

from formatting import sentence_clip
assert sentence_clip("First sentence. "+"Second is a lot longer than expected. "*15, 90).endswith(".")
