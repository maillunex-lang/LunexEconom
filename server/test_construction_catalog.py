"""Catalog must not silently make unbalanced/unpriced specializations buildable."""
import unittest
import sqlite3
from pathlib import Path
import construction_catalog
import economy
import game_server


class ConstructionCatalogTests(unittest.TestCase):
    def test_trade_catalog_has_33_unique_specializations(self):
        items = construction_catalog.view()["trade_specializations"]
        self.assertEqual(len(items), 33)
        self.assertEqual(len({item["id"] for item in items}), 33)
        self.assertEqual(sum(item["role"] == "wholesale" for item in items), 4)
        self.assertTrue(all(item["base_kind"] == "shop" for item in items))

    def test_existing_building_prices_unchanged(self):
        entries = construction_catalog.view()["base_buildings"]
        self.assertEqual({x["kind"]: x["build_cost"] for x in entries}, economy.BUILD_COST)
        self.assertEqual(set(game_server.KINDS), set(economy.BUILD_COST))

    def test_specialization_schema_is_additive_and_fk_safe(self):
        db = sqlite3.connect(":memory:")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("CREATE TABLE buildings(id TEXT PRIMARY KEY, owner TEXT, kind TEXT, x INTEGER, y INTEGER, created INTEGER)")
        db.execute("CREATE TABLE building_specializations(object_id TEXT PRIMARY KEY REFERENCES buildings(id) ON DELETE CASCADE,specialization TEXT NOT NULL)")
        db.execute("INSERT INTO buildings VALUES('a','test','shop',0,0,0)")
        db.execute("INSERT INTO building_specializations VALUES('a','grocery')")
        self.assertEqual(db.execute("SELECT specialization FROM building_specializations").fetchone()[0], "grocery")
        db.execute("DELETE FROM buildings WHERE id='a'")
        self.assertEqual(db.execute("SELECT count(*) FROM building_specializations").fetchone()[0], 0)
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("INSERT INTO building_specializations VALUES('missing','grocery')")
        db.close()

    def test_postgres_schema_declares_specializations(self):
        schema_source = (Path(__file__).parent / "postgres_db.py").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS building_specializations", schema_source)
        self.assertIn("ON DELETE CASCADE", schema_source)

    def test_new_specializations_are_not_buildable_yet(self):
        items = construction_catalog.view()["trade_specializations"]
        self.assertTrue(all(not item["enabled"] for item in items))
        for item in items:
            self.assertNotIn(item["id"], game_server.KINDS)


if __name__ == "__main__":
    unittest.main()
