"""Graph-level road connectivity regressions, independent of economic data."""
import sqlite3
import unittest
from unittest.mock import patch
import dev_road_connectivity as graph


class RoadConnectivityTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE roads(x INTEGER,y INTEGER,owner TEXT,created INTEGER)")
        self.db.execute("CREATE TABLE cells(x INTEGER,y INTEGER,object_id TEXT)")
        self.base = {(0, 0)}
        self.mock = patch("dev_road_connectivity._base_roads", return_value=self.base)
        self.mock.start()

    def tearDown(self):
        self.mock.stop()
        self.db.close()

    def road(self, *coords):
        self.db.executemany("INSERT INTO roads VALUES (?,?,'dev',0)", coords)

    def building(self, oid, *coords):
        self.db.executemany("INSERT INTO cells VALUES (?,?,?)", [(x, y, oid) for x, y in coords])

    def check(self, *removed):
        return graph.validate_removal(self.db, "?", removed)

    def test_bridge_removal_disconnects_network(self):
        self.road((1, 0), (2, 0), (3, 0))
        self.assertEqual(self.check((2, 0)), "road_network_disconnected")

    def test_alternate_path_allows_removal(self):
        self.road((1, 0), (2, 0), (0, 1), (1, 1), (2, 1))
        self.assertIsNone(self.check((1, 0)))

    def test_multi_cell_removal_breaks_alternate_path(self):
        self.road((1, 0), (2, 0), (0, 1), (1, 1), (2, 1))
        self.assertEqual(self.check((1, 0), (1, 1)), "road_network_disconnected")

    def test_dead_end_can_be_trimmed(self):
        self.road((1, 0), (2, 0), (3, 0))
        self.assertIsNone(self.check((3, 0)))

    def test_last_building_entrance_cannot_be_removed(self):
        self.road((1, 0))
        self.building("shop", (2, 0))
        self.assertEqual(self.check((1, 0)), "building_access_lost")

    def test_building_with_second_entrance_is_safe(self):
        self.road((1, 0), (2, 0), (1, 1), (2, 1))
        self.building("shop", (3, 0), (3, 1))
        self.assertIsNone(self.check((2, 0)))

    def test_isolated_component_must_not_split(self):
        self.road((80, 80), (81, 80), (82, 80))
        self.assertEqual(self.check((81, 80)), "road_network_disconnected")

    def test_removing_nonexistent_road_is_noop(self):
        self.assertIsNone(self.check((44, 44)))


if __name__ == "__main__":
    unittest.main()