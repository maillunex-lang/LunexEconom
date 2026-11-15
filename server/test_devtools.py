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
        self.db.execute("CREATE TABLE chunks(cx INTEGER,y INTEGER,cy INTEGER,version INTEGER,PRIMARY KEY(cx,cy))")
        self.db.execute("CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT,cx INTEGER,cy INTEGER,version INTEGER,kind TEXT,payload TEXT)")
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

    def test_undo_restores_prior_terrain(self):
        first={"request_id":"c2c3ad2b-180e-4517-839c-c47e48dbd7cb","kind":"water","cells":[[1,2]]}
        second={"request_id":"6d1a31fd-099e-492b-a00c-feb6ce8354a5","kind":"tree","cells":[[1,2]]}
        self.assertEqual(devtools.terrain_set(self.db,"?","dev",first,"local")[0],200)
        self.assertEqual(devtools.terrain_set(self.db,"?","dev",second,"local")[0],200)
        result=devtools.undo(self.db,"?","dev",{"request_id":"b0f1e34b-cda2-4924-a687-a421c82f581d"},"local")
        self.assertEqual(result[0],200)
        self.assertEqual(self.db.execute("SELECT kind FROM terrain_edits WHERE x=1 AND y=2").fetchone()[0],"water")
        self.assertEqual(devtools.undo(self.db,"?","dev",{"request_id":"b0f1e34b-cda2-4924-a687-a421c82f581d"},"local")[1].get("replayed"),True)

    def test_grant_revoke_and_replay(self):
        payload={"request_id":"c2c3ad2b-180e-4517-839c-c47e48dbd7cb","kind":"tree","cells":[[1,2]]}
        self.assertEqual(devtools.terrain_set(self.db,"?","dev",payload,"127.0.0.1")[0],200)
        self.assertTrue(devtools.terrain_set(self.db,"?","dev",payload,"127.0.0.1")[1]["replayed"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM dev_actions").fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM adm_audit").fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT kind FROM events").fetchone()[0],"terrain_changed")
        self.db.execute("DELETE FROM dev_roles WHERE username='dev'")
        self.db.commit()
        self.assertEqual(devtools.terrain_set(self.db,"?","dev",dict(payload,request_id="6d1a31fd-099e-492b-a00c-feb6ce8354a5"),"127.0.0.1")[0],403)

if __name__=="__main__":
    unittest.main()