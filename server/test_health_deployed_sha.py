"""Regression checks for the public deployed revision marker."""
import os
import tempfile
import unittest
from unittest import mock

import game_server


class HealthDeployedShaTests(unittest.TestCase):
    def test_valid_deployed_sha(self):
        with tempfile.NamedTemporaryFile(mode="w", encoding="ascii") as marker:
            marker.write("a" * 40 + "\n")
            marker.flush()
            with mock.patch.dict(os.environ, {"LUNEX_DEPLOYED_SHA_FILE": marker.name}):
                with mock.patch.object(game_server.sqlite_util, "open_db") as connect:
                    self.assertEqual(game_server.health_details()["commit"], "a" * 12)

    def test_missing_deployed_sha(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"LUNEX_DEPLOYED_SHA_FILE": directory + "/missing"}):
                with mock.patch.object(game_server.sqlite_util, "open_db"):
                    self.assertIsNone(game_server.health_details()["commit"])

    def test_invalid_deployed_sha(self):
        with tempfile.NamedTemporaryFile(mode="w", encoding="ascii") as marker:
            marker.write("not-a-commit")
            marker.flush()
            with mock.patch.dict(os.environ, {"LUNEX_DEPLOYED_SHA_FILE": marker.name}):
                with mock.patch.object(game_server.sqlite_util, "open_db"):
                    self.assertIsNone(game_server.health_details()["commit"])


if __name__ == "__main__":
    unittest.main()
