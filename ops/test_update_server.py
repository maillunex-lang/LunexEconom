import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import update_server as u


class UpdateServerTests(unittest.TestCase):
    def test_validate_rejects_syntax_error(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.py").write_text("def broken(:\n")
            with self.assertRaises(Exception):
                u.validate(Path(d), ["a.py"])

    def test_validate_accepts_valid_code(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.py").write_text("x = 1\n")
            u.validate(Path(d), ["a.py"])

    def test_server_file_pattern(self):
        self.assertTrue(u.SERVER_FILE.fullmatch("server/roads.py"))
        self.assertFalse(u.SERVER_FILE.fullmatch("server/../x.py"))
        self.assertFalse(u.SERVER_FILE.fullmatch("server/sub/x.py"))

    def test_rollback_on_failed_health(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            live, state = root / "live", root / "state"
            live.mkdir()
            (live / "game_server.py").write_text("old\n")
            names = ["game_server.py", "roads.py"]
            payload = {"game_server.py": b"new = 1\n", "roads.py": b"y = 2\n"}
            with mock.patch.object(u, "SERVER_DIR", live), mock.patch.object(u, "STATE", state), \
                 mock.patch.object(u, "fetch", side_effect=lambda url, limit=0: payload[url.rsplit("/", 1)[1]]), \
                 mock.patch.object(u, "restart") as restart, mock.patch.object(u, "healthy", return_value=False):
                with self.assertRaises(RuntimeError):
                    u.deploy("a" * 40, names)
            self.assertEqual((live / "game_server.py").read_text(), "old\n")
            self.assertFalse((live / "roads.py").exists())
            self.assertEqual(restart.call_count, 2)

    def test_successful_deploy_installs_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            live, state = root / "live", root / "state"
            live.mkdir()
            payload = {"game_server.py": b"new = 1\n"}
            with mock.patch.object(u, "SERVER_DIR", live), mock.patch.object(u, "STATE", state), \
                 mock.patch.object(u, "fetch", side_effect=lambda url, limit=0: payload[url.rsplit("/", 1)[1]]), \
                 mock.patch.object(u, "restart"), mock.patch.object(u, "healthy", return_value=True):
                u.deploy("a" * 40, ["game_server.py"])
            self.assertEqual((live / "game_server.py").read_text(), "new = 1\n")


if __name__ == "__main__":
    unittest.main()
