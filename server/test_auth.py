"""Isolated account API unit tests; no live database or user accounts touched."""
import os
import tempfile
import unittest
from unittest.mock import patch

class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"LUNEX_AUTH_DB": os.path.join(self.temp.name, "auth.sqlite3")})
        self.env.start()
        import auth
        self.auth = auth
        self.previous_db_path = auth.DB_PATH
        auth.DB_PATH = os.path.join(self.temp.name, "auth.sqlite3")
        self.auth._attempts.clear()

    def tearDown(self):
        self.auth.DB_PATH = self.previous_db_path
        self.env.stop()
        self.temp.cleanup()

    def test_register_login_profile_logout(self):
        code, data = self.auth.register({"username":"FarmOwner", "email":"owner@example.test", "password":"safe-test-password"}, "client-a")
        self.assertEqual(code, 200)
        token = data["token"]
        self.assertEqual(self.auth.profile(token)[0], 200)
        self.assertEqual(self.auth.login({"identifier":"owner@example.test", "password":"safe-test-password"}, "client-b")[0], 200)
        self.assertEqual(self.auth.login({"identifier":"FarmOwner", "password":"incorrect"}, "client-c")[0], 401)
        self.assertEqual(self.auth.logout(token)[0], 200)
        self.assertEqual(self.auth.profile(token)[0], 401)

    def test_duplicate_and_validation(self):
        payload = {"username":"Farmer123","email":"farmer@example.test","password":"safe-test-password"}
        self.assertEqual(self.auth.register(payload,"client-a")[0],200)
        self.assertEqual(self.auth.register(payload,"client-b")[0],409)
        self.assertEqual(self.auth.register({**payload,"username":"a"},"client-c")[0],400)

if __name__ == "__main__":
    unittest.main()
