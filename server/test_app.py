import unittest
from app import response, join

class FoundationTests(unittest.TestCase):
    def test_health(self):
        status, data = response("/health")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])

    def test_world_clock(self):
        status, data = response("/world")
        self.assertEqual(status, 200)
        self.assertEqual(data["month_seconds"], 86400)
        self.assertEqual(data["regions_active"], 0)

    def test_unknown_path(self):
        self.assertEqual(response("/bad")[0], 404)

    def test_session_validation(self):
        self.assertEqual(join("x")[0], 400)
        self.assertEqual(join("\nhello")[0], 400)
        status, data = join("Игрок")
        self.assertEqual(status, 201)
        self.assertEqual(len(data["session_id"]), 32)

if __name__ == "__main__":
    unittest.main()