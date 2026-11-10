import asyncio
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from access_control import parse_admin, requested_capability, TestAccess
from policy import OWNER_TWITCH_ID


class GrammarTests(unittest.TestCase):
    def test_grant_variations(self):
        samples=(
            ("!ask allow user TooOld4twitxh to invoke your commands.","grant","tooold4twitxh","all"),
            ("allow @viewerx to fact check","grant","viewerx","fact"),
            ("RoboRath, give this user 'viewerx' conversational abilities","grant","viewerx","conversation"),
            ("give @viewerx all AI abilities","grant","viewerx","all"),
            ("roborath grant viewerx research","grant","viewerx","research"),
            ("!rr access grant viewerx conversation","grant","viewerx","conversation"),
            ("allow @viewerx fact checking abilities","grant","viewerx","fact"),
            ("let @viewerx to use research","grant","viewerx","research"),
        )
        for sample,action,login,cap in samples:
            with self.subTest(sample=sample):
                intent=parse_admin(sample)
                self.assertIsNotNone(intent)
                self.assertEqual((intent.action,intent.login,intent.capability),(action,login,cap))

    def test_revoke_and_silence_variations(self):
        cases={
            "remove @viewerx from testing":("revoke","viewerx","all"),
            "revoke @viewerx fact checking abilities":("revoke","viewerx","fact"),
            "!rr access revoke viewerx research":("revoke","viewerx","research"),
            "stop talking":("mute","",""),
            "RoboRath, don't reply to anyone":("mute","",""),
            "stop talking, don't reply to anyone":("mute","",""),
            "Stop talking until I say so":("mute","",""),
            "Don't reply to anyone until I tell you to resume":("mute","",""),
            "start talking again":("resume","",""),
            "RoboRath resume talking":("resume","",""),
            "you can reply again":("resume","",""),
            "show access":("show","",""),
        }
        for sample,expected in cases.items():
            with self.subTest(sample=sample):
                intent=parse_admin(sample)
                self.assertIsNotNone(intent)
                self.assertEqual((intent.action,intent.login,intent.capability),expected)

    def test_noncommands_never_grant_or_mute(self):
        for sample in ("!ask explain why people say stop talking",
                       "!ask why should I allow @viewerx to fact check?",
                       "Does 'stop talking' sound rude?", "please add some context",
                       "RoboRath tell a story about granting access"):
            self.assertIsNone(parse_admin(sample),sample)

    def test_capability_recognition(self):
        for text,cap in (
            ("!ask hello","conversation"),("!search latest news","conversation"),
            ("!fact is that real","fact"),("!check this","fact"),
            ("!verify this","fact"),("!verify deep why this","research"),
            ("!research why","research"),("!rr help","help")):
            self.assertEqual(requested_capability(text),cap)
        self.assertIsNone(requested_capability("grant @viewerx conversation"))
        self.assertEqual(requested_capability("!ask"),"conversation")
        self.assertEqual(requested_capability("!research"),"research")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.access=TestAccess(self.db,OWNER_TWITCH_ID,broadcaster_id="67890")

    def tearDown(self):
        self.db.close()

    def test_default_deny_and_verified_owner(self):
        self.assertTrue(self.access.allowed("1414798445","fact"))
        self.assertFalse(self.access.allowed("55555","conversation"))
        self.assertFalse(self.access.allowed("55555","fact"))
        self.assertFalse(self.access.allowed("55555","research"))

    def test_grants_are_precise_and_revocable(self):
        a=self.access
        a.change("1414798445","g1","55555","viewerx","conversation",True)
        self.assertEqual(a.capabilities("55555"),{"conversation"})
        self.assertFalse(a.allowed("55555","fact"))
        a.change("1414798445","g2","55555","viewerx","all",True)
        self.assertEqual(a.capabilities("55555"),{"conversation","fact","research"})
        a.change("1414798445","g3","55555","viewerx","fact",False)
        self.assertEqual(a.capabilities("55555"),{"conversation","research"})
        a.change("1414798445","g4","55555","viewerx","all",False)
        self.assertFalse(a.capabilities("55555"))

    def test_no_privilege_esc_for_nonowner_or_spoofed_user(self):
        for bad_actor in ("55555","", "01414798445"):
            with self.assertRaises(PermissionError):
                self.access.change(bad_actor,"bad"+bad_actor,"66666","viewerx","all",True)
            with self.assertRaises(PermissionError):
                self.access.set_mute(bad_actor,"mute"+bad_actor,True)
        self.assertFalse(self.access.capabilities("66666"))

    def test_audit_idempotent_and_persistent_restart(self):
        a=self.access
        self.assertTrue(a.change("1414798445","id-1","55555","viewerx","fact",True))
        self.assertFalse(a.change("1414798445","id-1","55555","viewerx","fact",False))
        self.assertTrue(a.set_mute("1414798445","id-2",True))
        again=TestAccess(self.db,OWNER_TWITCH_ID,broadcaster_id="67890")
        self.assertTrue(again.muted())
        self.assertEqual(again.capabilities("55555"),{"fact"})
        self.assertFalse(again.allowed("55555","fact"))
        self.assertTrue(again.set_mute("1414798445","id-3",False))
        self.assertTrue(again.allowed("55555","fact"))

    def test_missing_owner_identity_fails_closed(self):
        bad=TestAccess(self.db,"")
        self.assertFalse(bad.allowed("55555","fact"))
        self.assertFalse(bad.can_receive("55555","!fact test",True))
        with self.assertRaises(PermissionError):
            bad.set_mute("","id",True)

    def test_qa_commands_strictly_scoped(self):
        self.access.change("1414798445","g1","55555","viewerx","conversation",True)
        self.assertFalse(self.access.can_receive("55555","!ask hello",True))
        self.assertTrue(self.access.can_receive("55555","!ask hello",False))
        self.assertFalse(self.access.can_receive("55555","!fact hello",True))
        self.assertFalse(self.access.can_receive("55555","!rr mario on",True))
        self.assertFalse(self.access.can_receive("55555","allow @otheruser all AI abilities",True))
        self.assertFalse(self.access.can_receive("55555","!rr remind 1m message",True))

    def test_owner_only_id_and_streamer_usage_without_admin(self):
        with self.assertRaises(ValueError):
            TestAccess(self.db,"12345")
        self.assertTrue(self.access.can_receive("67890","!verify claim",False))
        self.assertFalse(self.access.can_receive("67890","stop talking",False))
        self.assertFalse(self.access.is_owner("67890"))


if __name__=="__main__":
    unittest.main()
