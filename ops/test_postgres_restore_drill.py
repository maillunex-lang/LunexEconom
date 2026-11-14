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

    def test_server_port_differs_behind_a_container_port_mapping(self):
        with tempfile.TemporaryDirectory() as d:
            backup = Path(d) / "sample.dump"
            backup.write_bytes(b"sample")
            runner = Mock()
            runner.side_effect = [Mock(stdout="lunex_restore_admin|5432"), Mock(), Mock(stdout="3")]    # CI service: 5432 inside, 15551 outside
            self.assertEqual(run_drill(str(backup), "postgresql://localhost:15551/lunex_restore_admin",
                                       "lunex_restore_test_abc", runner=runner), 3)

    def test_production_port_reported_by_the_server_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            backup = Path(d) / "sample.dump"
            backup.write_bytes(b"sample")
            runner = Mock()
            runner.return_value.stdout = "lunex_restore_admin|15439"
            with self.assertRaises(ValueError):
                run_drill(str(backup), "postgresql://localhost:15551/lunex_restore_admin", "lunex_restore_test_abc", runner=runner)
            self.assertEqual(runner.call_count, 1)

    def test_garbled_answer_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            backup = Path(d) / "sample.dump"
            backup.write_bytes(b"sample")
            runner = Mock()
            runner.return_value.stdout = "nonsense"
            with self.assertRaises(ValueError):
                run_drill(str(backup), "postgresql://localhost:15551/lunex_restore_admin", "lunex_restore_test_abc", runner=runner)

    def test_empty_backup_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            backup = Path(d) / "empty.dump"
            backup.touch()
            with self.assertRaises(ValueError):
                run_drill(str(backup), "postgresql://localhost:15551/lunex_restore_admin",
                          "lunex_restore_test_abc")


if __name__ == "__main__":
    unittest.main()
