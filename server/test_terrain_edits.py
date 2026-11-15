"""Terrain edit persistence and validation tests (SQLite)."""
import sqlite3
import unittest
import terrain_edits

class TerrainEditsTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        terrain_edits.invalidate()
        terrain_edits.ensure(self.db)

    def tearDown(self):
        terrain_edits.invalidate()
        self.db.close()

    def test_chunk_and_manual_flag(self):
        self.assertEqual(terrain_edits.chunk(self.db, "?", 0, 0), {})
        terrain_edits.apply(self.db, "?", [(1, 2), (3, 4)], "water", "tester")
        self.assertEqual(terrain_edits.chunk(self.db, "?", 0, 0)[(1, 2)]["kind"], "water")
        self.assertTrue(terrain_edits.is_manual(self.db, "?", 1, 2))
        self.assertFalse(terrain_edits.is_manual(self.db, "?", 5, 5))

    def test_invalid_inputs(self):
        for cells, kind in [([(1, 2)], "lava"), ([(1.5, 2)], "water"), ([(0, 0)] * 26, "grass")]:
            with self.assertRaises(ValueError):
                terrain_edits.apply(self.db, "?", cells, kind)

    def test_override_replaces_prior_kind(self):
        terrain_edits.apply(self.db, "?", [(0, 0)], "tree")
        terrain_edits.apply(self.db, "?", [(0, 0)], "clear")
        self.assertEqual(terrain_edits.chunk(self.db, "?", 0, 0)[(0, 0)]["kind"], "clear")

if __name__ == "__main__":
    unittest.main()
