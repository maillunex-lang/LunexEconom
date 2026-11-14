import json
import os
import tempfile
import unittest
import uuid

import game_server
import roads


def rid():
    return str(uuid.uuid4())


def find_water():
    for x in range(1, 60):
        for y in range(1, 60):
            if roads.is_water(x, y):
                return x, y


class RoadRulesTests(unittest.TestCase):
    def test_base_grid(self):
        self.assertTrue(roads.is_base_road(0, 5))
        self.assertTrue(roads.is_base_road(19, 7))
        self.assertTrue(roads.is_base_road(-19, 7))
        self.assertFalse(roads.is_base_road(5, 5))

    def test_plan_touching_road_needs_no_path(self):
        err, path = roads.plan_access([(1, 5), (2, 5)], set(), set(), 10000)
        self.assertIsNone(err)
        self.assertEqual(path, [])

    def test_plan_builds_path_to_nearest_road(self):
        fp = [(8, 10), (9, 10), (8, 11), (9, 11)]
        err, path = roads.plan_access(fp, set(), set(), 10000)
        self.assertIsNone(err)
        self.assertTrue(path)
        self.assertTrue(roads.is_base_road(*path[-1]))
        for a, b in zip(path, path[1:]):
            self.assertEqual(abs(a[0] - b[0]) + abs(a[1] - b[1]), 1)
        self.assertFalse(set(path) & set(fp))

    def test_legacy_event_rows(self):
        item = roads.event_item(3, 0, 0, 2, "building_created",
                                json.dumps({"kind": "farm", "cells": [[1, 1]], "object_id": "a"}))
        self.assertEqual(item["kind"], "building_created")
        self.assertEqual(item["building_kind"], "farm")


class BuildRoadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = game_server.DB
        game_server.DB = os.path.join(self.tmp.name, "w.sqlite3")

    def tearDown(self):
        game_server.DB = self.old
        self.tmp.cleanup()

    def build(self, kind, x, y, request_id=None):
        return game_server.build("tester", {"kind": kind, "x": x, "y": y, "request_id": request_id or rid()})

    def test_build_far_from_road_creates_road(self):
        status, res = self.build("factory", 8, 10)
        self.assertEqual(status, 201, res)
        self.assertGreater(res["road_cells"], 0)
        kinds = [e["kind"] for e in res["events"]]
        self.assertIn("building_created", kinds)
        self.assertIn("road_changed", kinds)
        building = next(e for e in res["events"] if e["kind"] == "building_created")
        self.assertEqual(building["building_kind"], "factory")
        # chunk versions increase by one per event within a chunk
        seen = {}
        for e in res["events"]:
            key = (e["cx"], e["cy"])
            self.assertEqual(e["version"], seen.get(key, 0) + 1)
            seen[key] = e["version"]
        # snapshot contains the road and the building
        found = []
        for cx in range(-1, 2):
            for cy in range(-1, 2):
                found += game_server.chunk(cx, cy)[1]["cells"]
        self.assertEqual(sum(1 for c in found if c["kind"] == "road_changed"), res["road_cells"])
        self.assertTrue(any(c["kind"] == "building_created" and c["building_kind"] == "factory" for c in found))

    def test_idempotent_request(self):
        r = rid()
        s1, a = self.build("farm", 8, 10, r)
        s2, b = self.build("farm", 8, 10, r)
        self.assertEqual((s1, s2), (201, 200))
        self.assertEqual(a, b)

    def test_second_building_reuses_road(self):
        s1, a = self.build("farm", 8, 10)
        s2, b = self.build("farm", 8, 13)
        self.assertEqual((s1, s2), (201, 201))
        self.assertLessEqual(b["road_cells"], a["road_cells"] + 4)

    def test_rejections(self):
        self.assertEqual(self.build("farm", 8, 10)[0], 201)
        self.assertEqual(self.build("farm", 8, 10)[1]["error"], "occupied")
        self.assertEqual(self.build("farm", 0, 10)[1]["error"], "road_overlap")
        wx, wy = find_water()
        self.assertEqual(self.build("farm", wx, wy)[1]["error"], "water")

    def test_events_endpoint_keeps_event_type(self):
        self.build("farm", 8, 10)
        status, data = game_server.events(0)
        self.assertEqual(status, 200)
        self.assertEqual({e["kind"] for e in data["events"]} - {"building_created", "road_changed"}, set())


if __name__ == "__main__":
    unittest.main()
