"""Regression tests for isolated runtime config, active month and rollback."""
import json
import os
import sqlite3
import tempfile
import time
import unittest
from unittest import mock

import admin_api
import balance
import live_config_api
import runtime_config

class RuntimeConfigTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        admin_api.ensure(self.db, "?")
        self.db.execute("CREATE TABLE world_clock(id INTEGER PRIMARY KEY,epoch BIGINT NOT NULL,month_seconds BIGINT NOT NULL,base_index BIGINT NOT NULL)")
        self.db.execute("INSERT INTO world_clock VALUES(1,1000,60,0)")
        runtime_config.ensure(self.db,"?")
        live_config_api.ensure(self.db,"?")
        self.now = 1001

    def tearDown(self):
        runtime_config.release()
        runtime_config.invalidate()
        self.db.close()

    def test_empty_database_preserves_defaults_and_env(self):
        self.assertEqual(runtime_config.snapshot(self.db)["revision"], 0)
        self.assertFalse(balance.get("HOUSEHOLDS_ENABLED"))
        self.assertEqual(balance.get("BASE_WAGE"), balance.PARAMS["BASE_WAGE"])
        self.assertEqual(runtime_config.values(self.db), {})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM runtime_config_values").fetchone()[0], 0)

    def test_strict_types_ranges_and_unknown_names(self):
        bad = [{"UNRECOGNIZED": 1}, {"HOUSEHOLDS_ENABLED": 1},
               {"POPULATION_SCALE": -1}, {"BASE_WAGE": 1e99},
               {"HH_SAVINGS_PPM": "100"}, {"BANKS_ENABLED": "on"}]
        for changes in bad:
            with self.assertRaises(ValueError):
                runtime_config.change(self.db, "?", changes, "tester", "127.0.0.1", self.now, confirmed=True)
        self.assertEqual(runtime_config.snapshot(self.db)["revision"], 0)

    def test_confirmation_and_month_boundary(self):
        with self.assertRaisesRegex(ValueError, "confirmation_required"):
            runtime_config.change(self.db, "?", {"HOUSEHOLDS_ENABLED": True}, "test", "-", self.now)
        out = runtime_config.change(self.db, "?", {"HOUSEHOLDS_ENABLED": True}, "test", "-", self.now, confirmed=True)
        self.assertEqual(out["revision"], 1)
        self.assertFalse(runtime_config.values(self.db, 0).get("HOUSEHOLDS_ENABLED", False))
        runtime_config.synchronize(self.db, 0)
        self.assertFalse(balance.get("HOUSEHOLDS_ENABLED"))
        runtime_config.synchronize(self.db, 1)
        self.assertTrue(balance.get("HOUSEHOLDS_ENABLED"))
        with self.assertRaisesRegex(ValueError, "revision_conflict"):
            runtime_config.change(self.db, "?", {"HOUSEHOLDS_ENABLED": False}, "test", "-", self.now, confirmed=True, expected_revision=0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM adm_audit").fetchone()[0], 1)

    def test_revisions_and_rollback(self):
        runtime_config.change(self.db,"?",{"HOUSEHOLDS_ENABLED":True},"a","-",self.now,confirmed=True)
        runtime_config.change(self.db,"?",{"HOUSEHOLDS_ENABLED":False},"b","-",self.now,confirmed=True)
        self.assertEqual(len(runtime_config.revisions(self.db)), 2)
        result = runtime_config.rollback(self.db,"?",1,"a","-",self.now,confirmed=True)
        self.assertEqual(result["revision"],3)
        self.assertEqual(result["values"]["HOUSEHOLDS_ENABLED"]["value"], True)
        self.assertEqual(len(runtime_config.revisions(self.db)), 3)

    def test_client_update_rejects_invalid_payload_and_stale_revision(self):
        with self.assertRaisesRegex(ValueError, "invalid_changes"):
            runtime_config.client_update(self.db,"?",None,"admin","-",self.now,confirmed=True)
        runtime_config.client_update(self.db,"?",{"texts":{"hq_title":"Центр"}},
                                     "admin","-",self.now,confirmed=True,expected_revision=0)
        with self.assertRaisesRegex(ValueError, "revision_conflict"):
            runtime_config.client_update(self.db,"?",{"min_version":2},
                                         "admin","-",self.now,confirmed=True,expected_revision=0)
        self.assertEqual(runtime_config.client_settings(self.db)["min_version"],0)

    def test_household_monthly_integration_toggle(self):
        import households
        # Minimal schema is enough for the OFF path; a full disposable game
        # database is required to test the ON path's actual writes.
        from unittest import mock
        import game_server
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(game_server,"DB",folder+"/world.sqlite3"):
                with game_server.connect() as db:
                    db.execute("INSERT OR REPLACE INTO world_clock(id,epoch,month_seconds,base_index) VALUES(1,1000,60,0)")
                    runtime_config.change(db,"?",{"HOUSEHOLDS_ENABLED":True},"admin","-",1001,confirmed=True)
                    runtime_config.synchronize(db,0)
                    households.monthly(db,"?",0,1001)
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM household_months").fetchone()[0],0)
                    runtime_config.synchronize(db,1)
                    households.monthly(db,"?",1,1061)
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM household_months").fetchone()[0],1)
                    runtime_config.change(db,"?",{"HOUSEHOLDS_ENABLED":False},"admin","-",1061,confirmed=True)
                    runtime_config.synchronize(db,2)
                    households.monthly(db,"?",2,1121)
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM household_months").fetchone()[0],1)

    def test_client_stages_signed_release(self):
        original = runtime_config.client_settings(self.db)
        outcome = runtime_config.client_update(self.db,"?",{"texts":{"hq_title":"Компания"}},"admin","-",self.now,confirmed=True)
        self.assertEqual(outcome["revision"],1)
        self.assertEqual(runtime_config.client_settings(self.db)["texts"]["hq_title"], "Компания")
        self.assertEqual(live_config_api.public(self.db,"?")[0], 503)
        self.assertEqual(original["min_version"], 0)

if __name__ == "__main__":
    unittest.main()
