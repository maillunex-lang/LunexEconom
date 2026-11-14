"""Additive health contract tests; no live server or production database."""
import os
import unittest
import tempfile
from unittest.mock import patch
import game_server


class HealthTests(unittest.TestCase):
    def test_legacy_contract_and_sqlite_probe(self):
        with tempfile.NamedTemporaryFile(mode="w", encoding="ascii") as marker:
            marker.write("a" * 40 + "\n")
            marker.flush()
            with patch.dict(os.environ, {"LUNEX_DB_ENGINE": "sqlite", "LUNEX_DEPLOYED_SHA_FILE": marker.name}):
                with patch.object(game_server.sqlite_util, "open_db") as open_db:
                    open_db.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = (1,)
                    result = game_server.health_details()
        self.assertEqual(result["ok"], True)
        self.assertEqual(result["service"], "lunexeconom-game")
        self.assertEqual(result["version"], "0.2.0")
        self.assertEqual(result["commit"], "a" * 12)
        self.assertEqual(result["database"], {"engine": "sqlite", "status": "ok"})
        open_db.assert_called_once_with(game_server.DB)

    def test_database_failure_does_not_leak_exception(self):
        with patch.dict(os.environ, {"LUNEX_DB_ENGINE": "sqlite", "LUNEX_DEPLOYED_SHA_FILE": "/nonexistent/deployed-sha"}, clear=False):
            with patch.object(game_server.sqlite_util, "open_db", side_effect=RuntimeError("password=secret")):
                result = game_server.health_details()
        self.assertEqual(result["database"]["status"], "unavailable")
        self.assertIsNone(result["commit"])
        self.assertNotIn("secret", str(result))

    def test_postgres_probe(self):
        with patch.dict(os.environ, {"LUNEX_DB_ENGINE": "postgres"}):
            with patch.object(game_server, "postgres_db", create=True) as pg:
                pg.connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = (1,)
                self.assertEqual(game_server.health_details()["database"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
