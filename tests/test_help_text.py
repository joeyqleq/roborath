import unittest
from help_text import PAGES, TOPICS, help_response
from access_control import requested_capability
from irc_adapter import sanitize_public_reply


class HelpTextTests(unittest.TestCase):
    def test_pages_and_topics_are_short_concrete_chat_text(self):
        for page, text in PAGES.items():
            self.assertLessEqual(len(text.encode("utf-8")), 420, page)
            self.assertNotRegex(text.replace("=>", ""), r"[<>{}]")
            self.assertIn("!", text)
        for topic, text in TOPICS.items():
            with self.subTest(topic=topic):
                self.assertLessEqual(len(text.encode("utf-8")), 420)
                self.assertNotRegex(text.replace("=>", ""), r"[<>{}]")
        self.assertIn("offline", help_response("!rr help", specialist_enabled=False))

    def test_all_requested_help_routes_exist(self):
        for page in range(1, 5):
            self.assertEqual(help_response(f"!rr help {page}"), PAGES[page])
        for topic in ("ask", "search", "verify", "fact", "research", "mario", "alerts",
                      "triggers", "reminders", "privacy", "permissions", "admin"):
            self.assertEqual(help_response(f"!rr help {topic}"), TOPICS[topic])
        for command in ("!rr commands", "!rr commands 1"):
            self.assertEqual(help_response(command), PAGES[1])

    def test_unknown_page_falls_back_without_placeholder_syntax(self):
        result = help_response("!rr help 9")
        self.assertIn("1, 2, 3 or 4", result)
        self.assertNotRegex(result, r"[<>{}]")

    def test_all_help_fits_wire_budget_including_maximum_username_and_owner_title(self):
        for text in [*PAGES.values(),*TOPICS.values(),help_response('!rr help',specialist_enabled=False)]:
            wire='@'+'u'*25+' Boss, '+sanitize_public_reply(text)
            self.assertLessEqual(len(wire.encode()),420)
            self.assertNotIn('\n',wire)
            self.assertNotIn('<question>',wire)
        for topic in TOPICS:
            self.assertEqual(requested_capability('!rr help '+topic),'help',topic)


if __name__ == "__main__":
    unittest.main()
