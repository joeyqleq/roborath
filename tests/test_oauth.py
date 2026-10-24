import os
import tempfile
import unittest
from pathlib import Path
from twitch_auth import write_token_file,read_token_file,check_identity

class OAuthTests(unittest.TestCase):
    def test_private_token_file(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"private"/"oauth.json"
            write_token_file(path,{"access_token":"dummy","refresh_token":"dummy2"})
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            self.assertEqual(read_token_file(path)["access_token"],"dummy")
    def test_refuse_public_token_file(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"oauth.json"
            path.write_text('{"access_token":"test"}')
            path.chmod(0o644)
            with self.assertRaises(PermissionError):read_token_file(path)
    def test_verify_immutable_bot_identity(self):
        entry={"client_id":"devapp","user_id":"123456","login":"roborath",
               "scopes":["chat:read","chat:edit"]}
        self.assertEqual(check_identity(entry,"devapp"),"123456")
        for patch in ({"client_id":"fake"},{"login":"joeyleq"},{"user_id":"spoofed"},
                      {"scopes":["chat:read"]}):
            with self.subTest(patch=patch):
                with self.assertRaises(PermissionError):
                    check_identity({**entry,**patch},"devapp")
if __name__=="__main__":unittest.main()
