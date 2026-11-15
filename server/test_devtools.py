"""Developer terrain endpoint permissions and idempotency."""
import json
import sqlite3
import unittest
import devtools
from unittest.mock import patch
import admin_api

class DeveloperToolsTests(unittest.TestCase):
    def setUp(self):
        self.role_patcher=patch("devtools.accounts_admin.is_developer", side_effect=lambda username: self.db.execute("SELECT 1 FROM dev_roles WHERE username=?", (username,)).fetchone() is not None)
        self.db=sqlite3.connect(":memory:")
        self.role_patcher.start()
        self.db.execute("CREATE TABLE users(username TEXT PRIMARY KEY)")
        self.db.executemany("INSERT INTO users VALUES (?)",[("dev",),("player",)])
        self.db.execute("CREATE TABLE chunks(cx INTEGER,cy INTEGER,version INTEGER,PRIMARY KEY(cx,cy))")
        self.db.execute("CREATE TABLE cells(x INTEGER,y INTEGER,object_id TEXT,PRIMARY KEY(x,y))")
        self.db.execute("CREATE TABLE buildings(id TEXT PRIMARY KEY,owner TEXT,kind TEXT,x INTEGER,y INTEGER,created INTEGER)")
        self.db.execute("CREATE TABLE building_deposits(object_id TEXT,deposit_id TEXT,resource TEXT)")
        self.db.execute("CREATE TABLE building_ops(object_id TEXT,owner TEXT,kind TEXT,start_month INTEGER,start_permille INTEGER)")
        self.db.execute("CREATE TABLE building_dimensions(object_id TEXT,width INTEGER,height INTEGER,equipment_level INTEGER)")
        self.db.execute("CREATE TABLE building_specializations(object_id TEXT,specialization TEXT)")
        self.db.execute("CREATE TABLE ledger_entries(tx_id TEXT,account TEXT,amount INTEGER)")
        self.db.execute("CREATE TABLE roads(x INTEGER,y INTEGER,owner TEXT,created INTEGER,PRIMARY KEY(x,y))")
        self.db.execute("CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT,cx INTEGER,cy INTEGER,version INTEGER,kind TEXT,payload TEXT)")
        admin_api.ensure(self.db,"?")
        devtools.ensure(self.db,"?")
        self.db.execute("CREATE TABLE dev_roles(username TEXT PRIMARY KEY, granted_at INTEGER)")
        self.db.execute("INSERT INTO dev_roles(username,granted_at) VALUES ('dev',0)")
        self.db.commit()

    def tearDown(self):
        self.role_patcher.stop()
        self.db.close()

    def test_replay_must_match_actor_and_action(self):
        request_id="c2c3ad2b-180e-4517-839c-c47e48dbd7cb"
        payload={"request_id":request_id,"kind":"tree","cells":[[1,2]]}
        self.assertEqual(devtools.terrain_set(self.db,"?","dev",payload,"local")[0],200)
        self.db.execute("INSERT INTO dev_roles VALUES ('other',0)")
        self.assertEqual(devtools.terrain_set(self.db,"?","other",payload,"local")[1]["error"],"request_id_conflict")
        self.assertEqual(devtools.terrain_set(self.db,"?","dev",payload,"local")[1]["replayed"],True)

    def test_player_forbidden(self):
        payload={"request_id":"c2c3ad2b-180e-4517-839c-c47e48dbd7cb","kind":"water","cells":[[1,2]]}
        self.assertEqual(devtools.terrain_set(self.db,"?","player",payload,"127.0.0.1")[0],403)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM terrain_edits").fetchone()[0],0)

    def test_create_city_social_building_without_ledger(self):
        import economy
        payload={"request_id":"c2c3ad2b-180e-4517-839c-c47e48dbd7cb","kind":"park","x":11,"y":12}
        status,result=devtools.building_create(self.db,"?","dev",payload,"local")
        self.assertEqual(status,200,result)
        self.assertEqual(self.db.execute("SELECT owner,kind FROM buildings WHERE id=?", (result["object_id"],)).fetchone(),(economy.CITY,"park"))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0],0)
        self.assertTrue(devtools.building_create(self.db,"?","dev",payload,"local")[1]["replayed"])
        undo={"request_id":"b0f1e34b-cda2-4924-a687-a421c82f581d"}
        self.assertEqual(devtools.undo(self.db,"?","dev",undo,"local")[0],200)
        self.assertIsNone(self.db.execute("SELECT id FROM buildings WHERE id=?", (result["object_id"],)).fetchone())
        forbidden=dict(payload,request_id="6d1a31fd-099e-492b-a00c-feb6ce8354a5",owner="player")
        self.assertEqual(devtools.building_create(self.db,"?","dev",forbidden,"local")[1]["error"],"city_only")

    def test_demolish_removes_building_without_ledger(self):
        self.db.execute("INSERT INTO buildings VALUES ('b1','player','shop',11,12,0)")
        self.db.execute("INSERT INTO cells VALUES (11,12,'b1')")
        self.db.execute("INSERT INTO building_ops VALUES ('b1','player','shop',0,0)")
        payload={"request_id":"c2c3ad2b-180e-4517-839c-c47e48dbd7cb","object_id":"b1"}
        status,result=devtools.building_demolish(self.db,"?","dev",payload,"local")
        self.assertEqual(status,200,result)
        self.assertIsNone(self.db.execute("SELECT id FROM buildings WHERE id='b1'").fetchone())
        self.assertIsNone(self.db.execute("SELECT object_id FROM building_ops WHERE object_id='b1'").fetchone())
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0],0)
        self.assertTrue(devtools.building_demolish(self.db,"?","dev",payload,"local")[1]["replayed"])
        status,result=devtools.undo(self.db,"?","dev",{"request_id":"b0f1e34b-cda2-4924-a687-a421c82f581d"},"local")
        self.assertEqual(status,200,result)
        self.assertEqual(self.db.execute("SELECT owner,kind FROM buildings WHERE id='b1'").fetchone(),("player","shop"))
        self.assertEqual(self.db.execute("SELECT owner FROM building_ops WHERE object_id='b1'").fetchone(),("player",))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0],0)

    def test_move_preserves_owner_and_rejects_overlap(self):
        self.db.execute("INSERT INTO buildings VALUES ('b1','player','shop',11,12,0)")
        self.db.execute("INSERT INTO cells VALUES (11,12,'b1')")
        self.db.execute("INSERT INTO cells VALUES (11,13,'b1')")
        payload={"request_id":"c2c3ad2b-180e-4517-839c-c47e48dbd7cb","object_id":"b1","x":15,"y":16}
        self.assertEqual(devtools.building_move(self.db,"?","dev",payload,"local")[0],200)
        self.assertEqual(self.db.execute("SELECT owner,x,y FROM buildings WHERE id='b1'").fetchone(),("player",15,16))
        self.assertEqual(devtools.building_move(self.db,"?","dev",payload,"local")[1]["replayed"],True)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM cells WHERE object_id='b1'").fetchone()[0],2)
        undo={"request_id":"b0f1e34b-cda2-4924-a687-a421c82f581d"}
        self.assertEqual(devtools.undo(self.db,"?","dev",undo,"local")[0],200)
        self.assertEqual(self.db.execute("SELECT x,y FROM buildings WHERE id='b1'").fetchone(),(11,12))
        self.assertTrue(devtools.undo(self.db,"?","dev",undo,"local")[1]["replayed"])
        self.db.execute("INSERT INTO cells VALUES (20,20,'other')")
        blocked=dict(payload,request_id="6d1a31fd-099e-492b-a00c-feb6ce8354a5",x=20,y=20)
        self.assertEqual(devtools.building_move(self.db,"?","dev",blocked,"local")[1]["error"],"occupied")

    def test_move_rejects_incompatible_zone(self):
        self.db.execute("INSERT INTO buildings VALUES ('b1','player','shop',11,12,0)")
        self.db.execute("INSERT INTO cells VALUES (11,12,'b1')")
        payload={"request_id":"c2c3ad2b-180e-4517-839c-c47e48dbd7cb","object_id":"b1","x":30,"y":30}
        with patch("zoning.check", return_value=("industrial",("center","suburb"))):
            status,result=devtools.building_move(self.db,"?","dev",payload,"local")
        self.assertEqual(status,409,result)
        self.assertEqual(result["error"],"invalid_destination_zone")
        self.assertEqual(self.db.execute("SELECT x,y FROM buildings WHERE id='b1'").fetchone(),(11,12))

    def test_road_removal_protects_adjacent_building(self):
        self.db.execute("INSERT INTO buildings VALUES ('b1','player','shop',12,12,0)")
        self.db.execute("INSERT INTO cells VALUES (12,12,'b1')")
        self.db.execute("INSERT INTO roads VALUES (11,12,'dev',0)")
        payload={"request_id":"c2c3ad2b-180e-4517-839c-c47e48dbd7cb","operation":"remove","cells":[[11,12]]}
        status,result=devtools.roads_set(self.db,"?","dev",payload,"local")
        self.assertEqual(status,409,result)
        self.assertEqual(result["error"],"building_access_road")
        self.assertIsNotNone(self.db.execute("SELECT 1 FROM roads WHERE x=11 AND y=12").fetchone())

    def test_roads_add_remove_and_idempotency(self):
        add={"request_id":"c2c3ad2b-180e-4517-839c-c47e48dbd7cb","operation":"add","cells":[[11,12]]}
        self.assertEqual(devtools.roads_set(self.db,"?","dev",add,"local")[0],200)
        self.assertTrue(devtools.roads_set(self.db,"?","dev",add,"local")[1]["replayed"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM roads").fetchone()[0],1)
        remove=dict(add,request_id="6d1a31fd-099e-492b-a00c-feb6ce8354a5",operation="remove")
        self.assertEqual(devtools.roads_set(self.db,"?","dev",remove,"local")[0],200)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM roads").fetchone()[0],0)
        self.assertEqual(devtools.undo(self.db,"?","dev",{"request_id":"b0f1e34b-cda2-4924-a687-a421c82f581d"},"local")[0],200)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM roads").fetchone()[0],1)

    def test_cannot_paint_occupied_or_road_cell(self):
        payload={"request_id":"c2c3ad2b-180e-4517-839c-c47e48dbd7cb","kind":"water","cells":[[1,2]]}
        self.db.execute("INSERT INTO cells VALUES (1,2,'building')")
        self.assertEqual(devtools.terrain_set(self.db,"?","dev",payload,"local")[1]["error"],"occupied")
        self.db.execute("DELETE FROM cells")
        self.db.execute("INSERT INTO roads VALUES (1,2,'city',0)")
        self.assertEqual(devtools.terrain_set(self.db,"?","dev",payload,"local")[1]["error"],"road_overlap")

    def test_undo_rejects_newer_same_cell_action(self):
        first={"request_id":"c2c3ad2b-180e-4517-839c-c47e48dbd7cb","kind":"tree","cells":[[1,2]]}
        second={"request_id":"6d1a31fd-099e-492b-a00c-feb6ce8354a5","kind":"tree","cells":[[1,2]]}
        self.assertEqual(devtools.terrain_set(self.db,"?","dev",first,"local")[0],200)
        self.assertEqual(devtools.terrain_set(self.db,"?","dev",second,"local")[0],200)
        self.db.execute("UPDATE dev_actions SET undone=1 WHERE id=?", (second["request_id"],))
        result=devtools.undo(self.db,"?","dev",{"request_id":"b0f1e34b-cda2-4924-a687-a421c82f581d"},"local")
        self.assertEqual(result[0],200)

    def test_undo_rejects_other_editors_changes(self):
        payload={"request_id":"c2c3ad2b-180e-4517-839c-c47e48dbd7cb","kind":"water","cells":[[1,2]]}
        self.assertEqual(devtools.terrain_set(self.db,"?","dev",payload,"local")[0],200)
        self.db.execute("UPDATE terrain_edits SET editor='other',kind='tree' WHERE x=1 AND y=2")
        result=devtools.undo(self.db,"?","dev",{"request_id":"b0f1e34b-cda2-4924-a687-a421c82f581d"},"local")
        self.assertEqual(result[1]["error"],"undo_conflict")
        self.assertEqual(self.db.execute("SELECT kind FROM terrain_edits WHERE x=1 AND y=2").fetchone()[0],"tree")

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