"""SQLite smoke tests for operator-only developer grants."""
import os
import sqlite3
import tempfile
import unittest
import accounts_admin

class DeveloperRoleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = sqlite3.connect(os.path.join(self.tmp.name, "accounts.db"))
        self.db.execute("CREATE TABLE users (username TEXT PRIMARY KEY)")
        self.db.execute("INSERT INTO users(username) VALUES ('alice'), ('bob')")
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_grant_revoke_and_list(self):
        self.assertFalse(accounts_admin.is_developer("alice", self.db))
        accounts_admin.set_developer("alice", True, self.db)
        self.assertTrue(accounts_admin.is_developer("alice", self.db))
        self.assertEqual(accounts_admin.list_developers(self.db), ["alice"])
        accounts_admin.set_developer("alice", False, self.db)
        self.assertFalse(accounts_admin.is_developer("alice", self.db))

    def test_unknown_account_rejected(self):
        with self.assertRaisesRegex(ValueError, "account_not_found"):
            accounts_admin.set_developer("unknown", True, self.db)

if __name__ == "__main__":
    unittest.main()
