"""Regression tests for staged building footprint and equipment metadata."""
import sqlite3
import unittest
import building_dimensions as d


class BuildingDimensionsTests(unittest.TestCase):
    def test_legacy_shapes_unchanged(self):
        for kind, shape in d.LEGACY_FOOTPRINTS.items():
            self.assertEqual(d.footprint(kind), shape)

    def test_square_choices(self):
        for kind, choices in d.SIZE_CHOICES.items():
            for size in choices:
                self.assertEqual(d.footprint(kind, size), (size, size))

    def test_unsupported_sizes_rejected(self):
        for kind, size in [("shop", 3), ("school", 1), ("factory", 4),
                           ("factory", True), ("factory", 2.0), ("unknown", 1)]:
            with self.assertRaises(ValueError):
                d.footprint(kind, size)

    def test_expand_only_to_larger_valid_footprint(self):
        self.assertTrue(d.can_expand("factory", 1, 2))
        self.assertTrue(d.can_expand("factory", 2, 3))
        self.assertFalse(d.can_expand("shop", 2, 3))
        self.assertFalse(d.can_expand("factory", 2, 1))
        self.assertFalse(d.can_expand("factory", 2, 2))

    def test_equipment_independent_from_footprint(self):
        self.assertTrue(d.can_upgrade_equipment(1, 2))
        self.assertTrue(d.can_upgrade_equipment(2, 3))
        self.assertFalse(d.can_upgrade_equipment(3, 4))
        self.assertFalse(d.can_upgrade_equipment(1, 1))
        self.assertFalse(d.can_upgrade_equipment(True, 2))

    def test_optional_dimensions_do_not_change_legacy_rows(self):
        db = sqlite3.connect(":memory:")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("CREATE TABLE buildings(id TEXT PRIMARY KEY, kind TEXT NOT NULL)")
        db.execute("CREATE TABLE building_dimensions(object_id TEXT PRIMARY KEY REFERENCES buildings(id) ON DELETE CASCADE,width INTEGER NOT NULL CHECK(width BETWEEN 1 AND 3),height INTEGER NOT NULL CHECK(height BETWEEN 1 AND 3),equipment_level INTEGER NOT NULL DEFAULT 1 CHECK(equipment_level BETWEEN 1 AND 3))")
        db.execute("INSERT INTO buildings VALUES('old','factory')")
        self.assertIsNone(db.execute("SELECT * FROM building_dimensions WHERE object_id='old'").fetchone())
        db.execute("INSERT INTO buildings VALUES('new','factory')")
        db.execute("INSERT INTO building_dimensions(object_id,width,height) VALUES('new',2,2)")
        self.assertEqual(db.execute("SELECT width,height,equipment_level FROM building_dimensions").fetchone(), (2, 2, 1))
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("INSERT INTO building_dimensions VALUES('old',4,4,1)")
        db.execute("DELETE FROM buildings WHERE id='new'")
        self.assertEqual(db.execute("SELECT count(*) FROM building_dimensions").fetchone()[0], 0)
        db.close()


if __name__ == "__main__":
    unittest.main()
