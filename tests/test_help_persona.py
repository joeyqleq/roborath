import asyncio
import os
import tempfile
import unittest
from pathlib import Path
import bridge
from bridge import Bridge
from prompts import CONVERSATION

class HelpAndToneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.keys = ("GT_TWITCH_DB", "ROBORATH_OWNER_TWITCH_USER_ID",
                     "ROBORATH_STREAMER_TWITCH_USER_ID",
                     "ROBORATH_OWNER_ONLY_TEST_MODE")
        self.old = {k: os.environ.get(k) for k in self.keys}
        self.oldpath = bridge.DB_PATH
        os.environ["GT_TWITCH_DB"] = str(Path(self.tmp.name) / "log.sqlite3")
        os.environ["ROBORATH_OWNER_TWITCH_USER_ID"] = "1414798445"
        os.environ["ROBORATH_STREAMER_TWITCH_USER_ID"] = "67890"
        os.environ["ROBORATH_OWNER_ONLY_TEST_MODE"] = "true"
        bridge.DB_PATH = os.environ["GT_TWITCH_DB"]
        self.bot = Bridge()
        self.messages = []
        async def reply(text, mid):
            self.messages.append(text)
        async def stream():
            return "fake-stream"
        self.bot.twitch_reply = reply
        self.bot.stream_id = stream

    def tearDown(self):
        asyncio.run(self.bot.http.aclose())
        self.bot.db.close()
        bridge.DB_PATH = self.oldpath
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def send(self, msg, mid):
        asyncio.run(self.bot.on_chat({
            "message_id": mid,
            "chatter_user_id": "1414798445",
            "chatter_user_login": "joeyleq",
            "message": {"text": msg},
        }))

    def test_help_pages_are_examples_not_template_syntax(self):
        self.send("!rr help", "h1")
        self.send("!rr help 2", "h2")
        self.assertEqual(len(self.messages), 2)
        for message in self.messages:
            self.assertNotIn("<", message)
            self.assertNotIn(">", message)
            self.assertNotIn("{", message)
            self.assertNotIn("}", message)
            self.assertIn("!", message)
            self.assertLess(len(message.encode("utf-8")), 421)
        self.assertIn("!ask tell me a joke", self.messages[0].casefold())
        self.assertIn("!rr mario", self.messages[1].casefold())

    def test_incomplete_commands_have_readable_examples(self):
        for i, name in enumerate(("ask", "search", "fact", "research"), 1):
            self.send("!" + name, "u" + str(i))
        self.assertEqual(len(self.messages), 4)
        for msg in self.messages:
            self.assertTrue(msg.startswith("Usage: "))
            self.assertNotIn("<", msg)
            self.assertNotIn("{", msg)

    def test_persona_allows_satires_not_unsupported_accusations(self):
        self.assertIn("political satire", CONVERSATION)
        self.assertIn("Mao", CONVERSATION)
        self.assertIn("Netanyahu", CONVERSATION)
        self.assertIn("Never fabricate", CONVERSATION)
        self.assertIn("Jewish people", CONVERSATION)

if __name__ == "__main__":
    unittest.main()
