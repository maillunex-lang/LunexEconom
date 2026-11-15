"""Developer terrain endpoint permissions and idempotency."""
import json
import sqlite3
import unittest
import devtools
import admin_api

class DeveloperToolsTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE users(username TEXT PRIMARY KEY)")
        self.db.executemany("INSERT INTO users VALUES (?)",[("dev",),("player",)])
        admin_api.ensure(self.db,"?")
        devtools.ensure(self.db,"?")
        self.db.execute("INSERT INTO dev_roles(username,granted_at) VALUES ('dev',0)")
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_player_forbidden(self):
        payload={"request_id":"c2c3ad2b-180e-4517-839c-c47e48dbd7cb","kind":"water","cells":[[1,2]]}
        self.assertEqual(devtools.terrain_set(self.db,"?","player",payload,"127.0.0.1")[0],403)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM terrain_edits").fetchone()[0],0)

    def test_grant_revoke_and_replay(self):
        payload={"request_id":"c2c3ad2b-180e-4517-839c-c47e48dbd7cb","kind":"tree","cells":[[1,2]]}
        self.assertEqual(devtools.terrain_set(self.db,"?","dev",payload,"127.0.0.1")[0],200)
        self.assertTrue(devtools.terrain_set(self.db,"?","dev",payload,"127.0.0.1")[1]["replayed"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM dev_actions").fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM adm_audit").fetchone()[0],1)
        self.db.execute("DELETE FROM dev_roles WHERE username='dev'")
        self.db.commit()
        self.assertEqual(devtools.terrain_set(self.db,"?","dev",dict(payload,request_id="6d1a31fd-099e-492b-a00c-feb6ce8354a5"),"127.0.0.1")[0],403)

if __name__=="__main__":
    unittest.main()