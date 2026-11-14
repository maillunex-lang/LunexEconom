import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from postgres_restore_drill import run_drill


class RestoreDrillTests(unittest.TestCase):
    def test_rejects_non_disposable_target(self):
        with self.assertRaises(ValueError):
            run_drill("missing.dump", "postgresql://localhost:15551/lunex_restore_admin", "lunexeconom")

    def test_requires_explicit_test_admin_database(self):
        with tempfile.TemporaryDirectory() as d:
            backup = Path(d) / "sample.dump"
            backup.write_bytes(b"sample")
            runner = Mock()
            runner.return_value.stdout = "lunexeconom|15551"
            with self.assertRaises(ValueError):
                run_drill(str(backup), "postgresql://localhost:15551/lunex_restore_admin",
                          "lunex_restore_test_abc", runner=runner)
            self.assertEqual(runner.call_count, 1)

    def test_successful_mocked_restore_and_table_check(self):
        with tempfile.TemporaryDirectory() as d:
            backup = Path(d) / "sample.dump"
            backup.write_bytes(b"sample")
            runner = Mock()
            runner.side_effect = [Mock(stdout="lunex_restore_admin|15551"),
                                  Mock(), Mock(stdout="14")]
            self.assertEqual(run_drill(str(backup),
                             "postgresql://localhost:15551/lunex_restore_admin",
                             "lunex_restore_test_abc", runner=runner), 14)
            self.assertEqual(runner.call_count, 3)

    def test_empty_backup_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            backup = Path(d) / "empty.dump"
            backup.touch()
            with self.assertRaises(ValueError):
                run_drill(str(backup), "postgresql://localhost:15551/lunex_restore_admin",
                          "lunex_restore_test_abc")


if __name__ == "__main__":
    unittest.main()
