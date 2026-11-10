"""Independent, deterministic offline adversarial checks for RoboRath.

This suite tests contracts at the public boundaries. It deliberately avoids
live providers, network access, credentials and production Twitch/Mattermost.
The seeded matrices produce hundreds of distinct inputs on every run.
"""
from __future__ import annotations

import asyncio
import random
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from access_control import TestAccess
from formatting import MAX_IRC_BYTES, UnsafeModelOutput, humanize, messages, validate_final_output
from policy import PolicyStore, parse_public
import irc_adapter


OWNER = "1414798445"
BROADCASTER = "777777777"


class AdversarialBoundaryTests(unittest.TestCase):
    def test_120_tool_artifact_shapes_never_reach_chat(self):
        """Malformed/internal tool payloads must fail closed as one answer."""
        wrappers = (
            "<think>{body}</think>",
            "<tool_call>{body}</tool_call>",
            "<think>planning</think> <tool_call>{body}</tool_call>",
            "```json\n{body}\n```",
            "<|tool_call|>{body}<|/tool_call|>",
            "<assistant to=search_tools>{body}</assistant>",
        )
        bodies = (
            '{"name":"search_tools","arguments":{"query":"{q}"}}',
            '{"tool":"web_search","arguments":{"query":"{q}"}}',
            '{"name":"browser","arguments":{"url":"https://example.test/{q}"}}',
            '{"role":"tool","content":"{q}"}',
        )
        for index, (wrapper, body) in enumerate(
            ( (w, b) for w in wrappers for b in bodies for _ in range(5) )
        ):
            with self.subTest(index=index):
                payload = body.replace("{q}", f"case-{index}")
                raw = wrapper.replace("{body}", payload)
                with self.assertRaises(UnsafeModelOutput):
                    validate_final_output(raw)

    def test_explicit_discussion_of_json_is_not_blanket_blocked(self):
        answer = 'JSON is a data format; for example, {"name":"RoboRath"}.'
        visible = humanize(answer)
        self.assertIn("JSON is a data format", visible)
        self.assertIn('"name"', visible)

    def test_150_unicode_outputs_respect_the_irc_byte_budget(self):
        rng = random.Random(20261110)
        atoms = ["🇱🇧", "🛰️", "é", "中", "مرحبا", "a", "🧪", "👨‍👩‍👧‍👦"]
        for case in range(150):
            text = "".join(rng.choice(atoms) for _ in range(40 + case * 3))
            with self.subTest(case=case):
                for capability in ("fact", "research", "help"):
                    result = messages(text, capability)
                    self.assertTrue(result)
                    self.assertLessEqual(len(result), 2 if capability == "research" else 1)
                    for part in result:
                        self.assertLessEqual(len(part.encode("utf-8")), MAX_IRC_BYTES)
                        part.encode("utf-8").decode("utf-8")

    def test_100_non_invocations_do_not_trigger_specialist_work(self):
        prefixes = (
            "quoted !fact", "!factoid", "!rr factoid", "@roborathish fact",
            "RoboRath said !research", "cheer !check", "?fact", "look at this: !fact",
            "<message>!research", "please don't !check",
        )
        suffixes = ("claim", "", "?", " claim", "\n!fact claim", " research", "\x01ACTION claim\x01", "📎")
        for index, text in enumerate(f"{prefix} {suffix}" for prefix in prefixes for suffix in suffixes):
            with self.subTest(index=index, text=text):
                self.assertIsNone(parse_public(text))

    def test_100_forged_admin_actions_cannot_mutate_access(self):
        db = sqlite3.connect(":memory:")
        try:
            access = TestAccess(db, OWNER)
            for index in range(100):
                actor = str(900000 + index)
                # A username that claims to be the owner is still an ordinary ID.
                with self.subTest(index=index):
                    with self.assertRaises(PermissionError):
                        access.change(actor, f"forged-{index}", str(500000 + index),
                                      "joeyleq", "all", True)
                    with self.assertRaises(PermissionError):
                        access.set_mute(actor, f"mute-{index}", True)
                    self.assertFalse(access.muted())
                    self.assertEqual(access.capabilities(str(500000 + index)), set())
            self.assertTrue(access.change(OWNER, "owner-grant", "123456", "viewerx", "all", True))
            self.assertEqual(access.capabilities("123456"), {"conversation", "fact", "research"})
        finally:
            db.close()

    def test_owner_and_streamer_quota_exemptions_do_not_depend_on_login(self):
        db = sqlite3.connect(":memory:", isolation_level=None)
        try:
            policy = PolicyStore(db, OWNER, BROADCASTER)
            for uid in (OWNER, BROADCASTER):
                for capability in ("fact", "research"):
                    for index in range(25):
                        with self.subTest(uid=uid, capability=capability, index=index):
                            result = policy.check_or_reserve(
                                uid, f"{uid}-{capability}-{index}", capability, "stream-qa", "2026-11-10"
                            )
                            self.assertTrue(result.allowed)
        finally:
            db.close()

    def test_owner_only_qa_suppresses_granted_and_streamer_ai_requests(self):
        db = sqlite3.connect(":memory:")
        try:
            access = TestAccess(db, OWNER, BROADCASTER)
            self.assertTrue(access.change(OWNER, "grant-viewer", "55123", "viewerx",
                                          "conversation", True))
            self.assertFalse(access.can_receive("55123", "!ask joke", strict=True))
            self.assertFalse(access.can_receive(BROADCASTER, "!ask joke", strict=True))
            self.assertTrue(access.can_receive(OWNER, "!ask joke", strict=True))
            self.assertTrue(access.set_mute(OWNER, "mute-owner", True))
            self.assertFalse(access.can_receive(OWNER, "!ask joke", strict=True))
        finally:
            db.close()

    def test_identity_config_rejects_names_and_malformed_numeric_ids(self):
        for owner, broadcaster in (
            ("joeyleq", BROADCASTER), (OWNER, "rath_bone"), ("", BROADCASTER),
            ("+1414798445", BROADCASTER),
            ("١٤١٤٧٩٨٤٤٥", BROADCASTER),
        ):
            with self.subTest(owner=owner, broadcaster=broadcaster):
                with self.assertRaises(ValueError):
                    PolicyStore(sqlite3.connect(":memory:"), owner, broadcaster)

    def test_wire_payload_includes_verified_mention_within_420_utf8_bytes(self):
        """Exercise the final IRC line, including address and command framing."""
        import bridge
        old_path = bridge.DB_PATH
        with tempfile.TemporaryDirectory() as temp:
            bridge.DB_PATH = str(Path(temp) / "qa.sqlite3")
            with patch.object(irc_adapter, "OWNER_ONLY_TEST", False), \
                 patch.object(irc_adapter, "CHANNEL", "qa_channel"), \
                 patch.object(irc_adapter, "THREADED_REPLIES", False):
                adapter = irc_adapter.IRCAdapter()

                class Socket:
                    def __init__(self): self.frames = []
                    async def send(self, frame): self.frames.append(frame)

                adapter.ws = Socket()
                adapter.last_send = -1e6
                adapter.bridge.access.change(OWNER,"wire-grant","55123","viewerx","conversation",True)
                adapter.bridge.db.execute("""INSERT INTO chat_events
                    (message_id,stream_id,twitch_user_id,twitch_login,created_utc,
                     request_text,status)
                    VALUES('wire-qa','stream-qa','55123','viewerx',
                           '2026-11-10T00:00:00Z','!ask hello','observed')""")
                adapter.bridge.db.commit()
                try:
                    asyncio.run(adapter.reply("中" * 500, "wire-qa"))
                    frame = adapter.ws.frames[0]
                    payload = frame.split(" :", 1)[1].removesuffix("\r\n")
                    self.assertTrue(payload.startswith("@viewerx "))
                    self.assertLessEqual(len(payload.encode("utf-8")), MAX_IRC_BYTES)
                    payload.encode("utf-8").decode("utf-8")
                finally:
                    adapter.bridge.db.close()
                    asyncio.run(adapter.bridge.http.aclose())
                    if hasattr(adapter.bridge.router, "http"):
                        asyncio.run(adapter.bridge.router.http.aclose())
        bridge.DB_PATH = old_path


if __name__ == "__main__":
    unittest.main()
