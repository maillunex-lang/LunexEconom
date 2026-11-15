"""BE-108: deterministic deposits, depletion, and the legacy-mine exception."""
import json
import os
import tempfile
import threading
import unittest
import uuid
from http.server import ThreadingHTTPServer
from unittest import mock
from urllib.request import urlopen
from urllib.error import HTTPError

import deposits
import game_server
import geo
import goods_catalog
import regions
import roads

DAY = 86400
T0 = 1_800_000_000


def rid():
    return str(uuid.uuid4())


class LayoutTests(unittest.TestCase):
    def test_layout_is_deterministic_and_avoids_water_roads_and_city_centres(self):
        first = deposits.layout()
        second = deposits.layout()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 20 * sum(deposits.COUNTS.values()))
        counts = {}
        centres = {(c["id"], int(c["x"]), int(c["y"])) for c in geo.cities()}
        by_city = {c["id"]: (int(c["x"]), int(c["y"])) for c in geo.cities()}
        for item in first:
            counts[item["resource"]] = counts.get(item["resource"], 0) + 1
            self.assertEqual(item["initial"], deposits.INITIAL[item["resource"]])
            self.assertEqual(regions.region_of(item["x"], item["y"]), item["region"])
            self.assertNotIn((item["region"], item["x"], item["y"]), centres)
            cx, cy = by_city[item["region"]]
            self.assertGreaterEqual(max(abs(item["x"] - cx), abs(item["y"] - cy)), 5)
            for dx in range(deposits.PAD):
                for dy in range(deposits.PAD):
                    self.assertFalse(roads.is_water(item["x"] + dx, item["y"] + dy))
                    self.assertFalse(roads.is_base_road(item["x"] + dx, item["y"] + dy))
        self.assertEqual(counts, {"oil": 40, "gas": 20, "sand": 20, "forest": 20})
        ids = [item["id"] for item in first]
        self.assertEqual(len(ids), len(set(ids)))


class DepositWorld(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = game_server.DB
        game_server.DB = os.path.join(self.tmp.name, "w.sqlite3")
        self.now = T0
        patch = mock.patch.object(game_server.time, "time", side_effect=lambda: self.now)
        patch.start()
        self.addCleanup(patch.stop)
        self.cursor = 0

    def tearDown(self):
        game_server.DB = self.old
        self.tmp.cleanup()

    def month(self, who="alice", n=1):
        self.now += DAY * n + 5
        return game_server.wallet(who)[1]

    def site(self):
        for _ in range(400):
            self.cursor += 1
            x, y = 2, 2 + 4 * self.cursor
            status, res = game_server.build("probe", {"kind": "farm", "x": x, "y": y, "request_id": rid()})
            if status == 201:
                game_server.sell("probe", {"object_id": res["object_id"], "request_id": rid()})
                return x, y
        self.fail("no free site")

    def oil_origin(self):
        with game_server.connect() as db:
            origins = deposits.open_origins(db, "?", "oil")
        self.assertGreater(len(origins), 0)
        return origins[0]

    def assert_ledger(self):
        with game_server.connect() as db:
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
        self.assertEqual((bad, total), ([], 0))


class BuildTests(DepositWorld):
    def test_well_requires_a_deposit_and_depletes_it(self):
        x, y, dep_id = self.oil_origin()
        off_x, off_y = self.site()
        status, res = game_server.build("alice", {"kind": "oil_well", "x": off_x, "y": off_y, "request_id": rid()})
        self.assertEqual((status, res.get("error")), (409, "no_deposit"))
        status, res = game_server.build("alice", {"kind": "oil_well", "x": x, "y": y, "request_id": rid()})
        self.assertEqual(status, 201, res)
        with game_server.connect() as db:
            before = db.execute("SELECT remaining FROM deposits WHERE id=?", (dep_id,)).fetchone()[0]
        self.assertEqual(before, deposits.INITIAL["oil"])
        self.month("alice")
        with game_server.connect() as db:
            after = db.execute("SELECT remaining FROM deposits WHERE id=?", (dep_id,)).fetchone()[0]
            supply = db.execute("SELECT supply FROM market_prices WHERE product='oil' AND month_index=0").fetchone()[0]
        self.assertEqual(before - after, supply)
        self.assertGreater(supply, 0)
        self.assertLessEqual(supply, goods_catalog.recipe("oil_well").capacity)
        self.assert_ledger()
        with game_server.connect() as db:
            db.execute("UPDATE deposits SET remaining=5 WHERE id=?", (dep_id,))
        self.month("alice")
        with game_server.connect() as db:
            left = db.execute("SELECT remaining FROM deposits WHERE id=?", (dep_id,)).fetchone()[0]
            supply = db.execute("SELECT supply FROM market_prices WHERE product='oil' AND month_index=1").fetchone()[0]
        self.assertEqual((left, supply), (0, 5))
        sold = game_server.sell("alice", {"object_id": res["object_id"], "request_id": rid()})
        self.assertEqual(sold[0], 201, sold[1])
        again = game_server.build("alice", {"kind": "oil_well", "x": x, "y": y, "request_id": rid()})
        self.assertEqual(again[1].get("error"), "no_deposit")

    def test_legacy_mine_builds_anywhere_and_does_not_deplete(self):
        x, y = self.site()
        with game_server.connect() as db:
            before = db.execute("SELECT COALESCE(SUM(remaining),0) FROM deposits").fetchone()[0]
        status, res = game_server.build("alice", {"kind": "mine", "x": x, "y": y, "request_id": rid()})
        self.assertEqual(status, 201, res)
        self.month("alice")
        with game_server.connect() as db:
            after = db.execute("SELECT COALESCE(SUM(remaining),0) FROM deposits").fetchone()[0]
            supply = db.execute("SELECT supply FROM market_prices WHERE product='oil' AND month_index=0").fetchone()[0]
        self.assertEqual(after, before)
        self.assertEqual(supply, 40)
        self.assert_ledger()

    def test_deposit_busy_when_a_live_building_holds_the_link(self):
        x, y, dep_id = self.oil_origin()
        farm_x, farm_y = self.site()
        status, farm = game_server.build("alice", {"kind": "farm", "x": farm_x, "y": farm_y, "request_id": rid()})
        self.assertEqual(status, 201, farm)
        with game_server.connect() as db:
            db.execute("INSERT INTO building_deposits(object_id,deposit_id,resource) VALUES(?,?,?)",
                       (farm["object_id"], dep_id, "oil"))
        status, res = game_server.build("bob", {"kind": "oil_well", "x": x, "y": y, "request_id": rid()})
        self.assertEqual((status, res.get("error"), res.get("deposit_id")), (409, "deposit_busy", dep_id))

    def test_bbox_query_is_inclusive(self):
        x, y, dep_id = self.oil_origin()
        with game_server.connect() as db:
            hit = deposits.query(db, "?", x, y, x, y)
            miss = deposits.query(db, "?", x + 50, y + 50, x + 60, y + 60)
        self.assertIn(dep_id, [item["id"] for item in hit["deposits"]])
        self.assertTrue(all(item["x"] > x + 60 or item["y"] > y + 60 or item["x"] + item["width"] <= x + 50
                            or item["y"] + item["height"] <= y + 50 for item in miss["deposits"]) or not miss["deposits"])
        self.assertIsNone(deposits.parse_bbox({}))
        self.assertIsNone(deposits.parse_bbox({"x0": ["0"], "y0": ["0"], "x1": ["3000"], "y1": ["1"]}))


class CatalogHttpTests(DepositWorld):
    def test_catalog_and_deposits_are_cacheable_json(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), game_server.Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:%d" % server.server_address[1]
        try:
            with urlopen(base + "/catalog/goods", timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Cache-Control"], "public, max-age=86400")
                payload = json.loads(response.read())
            self.assertEqual(payload["version"], 1)
            self.assertIn("bread", [g["id"] for g in payload["goods"]])
            self.assertIn("bread_plant", [r["kind"] for r in payload["recipes"]])
            self.assertTrue(payload["recipes"][[r["kind"] for r in payload["recipes"]].index("mine")]["legacy"])
            with urlopen(base + "/deposits?x0=0&y0=0&x1=30&y1=30", timeout=5) as response:
                self.assertEqual(response.headers["Cache-Control"], "public, max-age=300")
                box = json.loads(response.read())
            self.assertEqual(box["bbox"], [0, 0, 30, 30])
            self.assertIn("deposits", box)
            try:
                urlopen(base + "/deposits", timeout=5)
                self.fail("missing bbox should be 400")
            except HTTPError as exc:
                self.assertEqual(exc.code, 400)
                self.assertEqual(json.loads(exc.read())["error"], "invalid_query")
        finally:
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()


if __name__ == "__main__":
    unittest.main()
