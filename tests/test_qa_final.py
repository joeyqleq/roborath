"""Final owner-role and reliable-context regression checks.

The fixture strings below are synthetic paraphrases; no private transcript
content belongs in this repository.
"""
import unittest
import tempfile
from pathlib import Path
import asyncio
import sqlite3

from prompts import CONVERSATION
from prompts import OWNER_VOICE
from router import Ledger, Router
from scenarios import history_context
from access_control import TestAccess, parse_admin


class OwnerRoleTests(unittest.TestCase):
    def test_owner_is_addressed_as_boss_without_snark(self):
        class Reply:
            def raise_for_status(self): pass
            def json(self):
                return {"choices":[{"message":{"role":"assistant","content":"Understood."},"finish_reason":"stop"}],
                        "usage":{"prompt_tokens":20,"completion_tokens":2}}
        class HTTP:
            def __init__(self): self.requests=[]
            async def post(self,url,headers,json,timeout):
                self.requests.append(json)
                return Reply()
        for uid,login,expected in (("1414798445","joeyleq",True),
                                   ("555555","joeyleq",False),
                                   ("555555","viewerx",False)):
            with self.subTest(uid=uid,login=login,expected=expected), tempfile.TemporaryDirectory() as temp:
                ledger=Ledger(str(Path(temp)/"ledger.sqlite"))
                http=HTTP()
                router=Router({"NEBIUS_BASE_URL":"https://model.invalid/v1","NEBIUS_API_KEY":"fake"},
                              ledger,http,available_models={"NEBIUS":{"NousResearch/Hermes-4-405B"},"MERGE":set(),"NVIDIA":set()})
                asyncio.run(router.complete("answer plainly",actor_id=uid,owner_id="1414798445",
                                              actor_login=login,actor_role="owner" if login=="joeyleq" else "viewer"))
                system=http.requests[0]["messages"][0]["content"].casefold()
                if expected:
                    self.assertIn("joeyleq",system)
                    self.assertTrue(any(word in system for word in ("chairman", "boss", "captain", "leader", "comandante")))
                    self.assertTrue(any(word in system for word in ("loyal servant", "faithful servant", "loyal aide")))
                    self.assertTrue(any(word in system for word in ("respect", "deferential", "never insult")))
                    self.assertTrue(any(word in system for word in ("profanity", "swear", "dirty humor")))
                else:
                    self.assertNotIn(OWNER_VOICE.casefold(),system)
                ledger.db.close()


class ContextBoundaryTests(unittest.TestCase):
    def test_wait_trigger_is_not_an_answerable_food_question(self):
        turns = [
            ("Wait until I say banana before answering.", "Understood. I will wait for banana.", "chat"),
        ]
        history = history_context(turns)
        self.assertIn("banana", history.casefold())
        self.assertIn("wait", history.casefold())

    def test_answer_topic_shift_uses_latest_question_and_prior_wait_state(self):
        turns = [
            ("What is the capital of France?", "Paris.", "chat"),
            ("Wait until I say banana before answering.", "Understood. I will wait for banana.", "chat"),
        ]
        history = history_context(turns)
        self.assertIn("capital of France", history)
        self.assertIn("banana", history.casefold())
        self.assertNotIn("Apple", history)

    def test_search_followup_context_keeps_original_topic(self):
        turns = [
            ("What about the delay?", "NASA has an update.", "chat"),
            ("Find the latest official Artemis launch update.", "NASA reports a planned launch window. Source: nasa.gov", "search"),
        ]
        history = history_context(turns)
        self.assertIn("Artemis", history)
        self.assertIn("delay", history)


class OwnerWakeTests(unittest.TestCase):
    def test_wait_for_phrase_is_persisted_and_only_verified_owner_can_wake(self):
        db=sqlite3.connect(":memory:")
        try:
            access=TestAccess(db,"1414798445")
            intent=parse_admin("RoboRath, stop talking until I say banana")
            self.assertIsNotNone(intent)
            self.assertEqual((intent.action,intent.wake_phrase),("mute","banana"))
            self.assertTrue(access.set_mute("1414798445","mute-test",True,intent.wake_phrase))
            self.assertFalse(access.matches_wake_phrase("55555","banana"))
            self.assertFalse(access.matches_wake_phrase("1414798445","I said banana"))
            access2=TestAccess(db,"1414798445")
            self.assertTrue(access2.muted())
            self.assertTrue(access2.matches_wake_phrase("1414798445","banana"))
        finally:db.close()


if __name__ == "__main__":
    unittest.main()
