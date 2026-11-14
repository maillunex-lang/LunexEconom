import unittest
from api_load_test import validate_url, run


class LoadProbeTests(unittest.TestCase):
    def test_rejects_production_domain(self):
        with self.assertRaises(ValueError):
            validate_url("https://rikagro.ru/lunexeconom/health")

    def test_rejects_default_production_port(self):
        with self.assertRaises(ValueError):
            validate_url("http://127.0.0.1:18767/health")

    def test_rejects_mutating_routes(self):
        with self.assertRaises(ValueError):
            validate_url("http://127.0.0.1:19123/sell")

    def test_accepts_isolated_loopback(self):
        self.assertEqual(validate_url("http://127.0.0.1:19123"),
                         "http://127.0.0.1:19123/health")

    def test_rejects_unbounded_load(self):
        with self.assertRaises(ValueError):
            run("http://127.0.0.1:19123", requests=10000)


if __name__ == "__main__":
    unittest.main()
