import unittest
from health_monitor import check


class HealthMonitorTests(unittest.TestCase):
    def test_blocks_production_host(self):
        with self.assertRaises(ValueError):
            check("https://rikagro.ru/health")

    def test_blocks_production_port(self):
        with self.assertRaises(ValueError):
            check("http://127.0.0.1:18767/health")

    def test_blocks_mutating_path(self):
        with self.assertRaises(ValueError):
            check("http://127.0.0.1:19123/build")

    def test_blocks_credentials(self):
        with self.assertRaises(ValueError):
            check("http://user:pass@127.0.0.1:19123/health")


if __name__ == "__main__":
    unittest.main()