"""Materials, lorries, product grade, research and NPC builders (Grok6)."""
import os
import tempfile
import unittest
import uuid
from unittest import mock

import balance
import deposits
import economy
import game_server
import goods_catalog
import npc
import quality
import regions
import trucks
import zoning

DAY = 86400
T0 = 1_800_000_000


def rid():
    return str(uuid.uuid4())


class GradeTests(unittest.TestCase):
    def test_grade_three_is_a_neutral_price(self):
        self.assertEqual(quality.score(1, 3, 0), 3)
        self.assertEqual(quality.score(3, 3, 0), 5)
        self.assertEqual(quality.score(1, 1, 0), 2)
        self.assertEqual(quality.score(1, 5, 0), 4)
        self.assertEqual(quality.input_grade({}, {}), 3)
        self.assertEqual(quality.input_grade({"grain": 100}, {"grain": 5}), 5)
        self.assertEqual(quality.input_grade({"iron_ore": 40, "coal": 50}, {"iron_ore": 5, "coal": 3}), 4)
        self.assertEqual(quality.price_factor(3), 1.0)
        self.assertAlmostEqual(quality.price_factor(5), 1.1)
        self.assertAlmostEqual(quality.price_factor(1), 0.9)
        self.assertEqual(max(1, min(5, quality.score(9, 9, 9))), 5)


class WorldCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = game_server.DB
        game_server.DB = os.path.join(self.tmp.name, "w.sqlite3")
        self.now = T0
        patch = mock.patch.object(game_server.time, "time", side_effect=lambda: self.now)
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        game_server.DB = self.old
        self.tmp.cleanup()

    def sql(self, query, params=()):
        with game_server.connect() as db:
            return db.execute(query, params).fetchall()

    def books(self):
        bad = self.sql("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0")
        total = self.sql("SELECT COALESCE(SUM(balance),0) FROM wallets")[0][0]
        self.assertEqual(bad, [])
        self.assertEqual(int(total), 0)

    def test_no_fleet_keeps_the_legacy_tariff_and_a_fleet_is_capped(self):
        with game_server.connect() as db:
            ship, fee = trucks.take(db, "?", "nobody", "honey", "ufa", "sterlitamak", 10, 0)
            self.assertEqual(ship, 10)
            self.assertEqual(fee, 10 * regions.unit_cost("honey", "ufa", "sterlitamak"))
            db.execute("INSERT INTO company_trucks(owner,units,capacity_each) VALUES(?,?,?)", ("haul", 1, 40))
            ship, fee = trucks.take(db, "?", "haul", "honey", "ufa", "sterlitamak", 100, 0)
            self.assertEqual(ship, 40)
            self.assertGreater(fee, 0)
            self.assertLess(fee, 100 * regions.unit_cost("oil", "ufa", "sterlitamak"))
            again, _fee = trucks.take(db, "?", "haul", "honey", "ufa", "sibay", 10, 0)
            self.assertEqual(again, 0)

    def test_buying_a_lorry_and_starting_research_balance(self):
        status, body = game_server.trucks_buy("alice", {"count": 1, "request_id": rid()})
        self.assertEqual(status, 201, body)
        self.assertEqual(body["units"], 1)
        self.assertEqual(body["cost"], balance.DEFAULTS["TRUCK_PRICE"])
        request = rid()
        status, body = game_server.trucks_buy("bob", {"count": 2, "request_id": request})
        self.assertEqual(status, 201, body)
        replay = game_server.trucks_buy("bob", {"count": 2, "request_id": request})
        self.assertEqual(replay[0], 200)
        self.assertEqual(replay[1]["units"], body["units"])
        status, body = game_server.research_start("alice", {"track": "quality", "request_id": rid()})
        self.assertEqual(status, 201, body)
        self.assertEqual(body["status"], "active")
        dup = game_server.research_start("alice", {"track": "quality", "request_id": rid()})
        self.assertEqual(dup[0], 409)
        self.assertEqual(dup[1]["error"], "research_exists")
        bad = game_server.research_start("alice", {"track": "magic", "request_id": rid()})
        self.assertEqual(bad[0], 400)
        view = self.sql("SELECT track, status FROM company_research WHERE owner='alice'")
        self.assertEqual(view, [("quality", "active")])
        self.books()

    def test_equipment_raises_the_clearing_price_and_the_books_still_balance(self):
        status, res = game_server.build("alice", {"kind": "farm", "x": 8, "y": 40, "request_id": rid()})
        self.assertEqual(status, 201, res)
        with game_server.connect() as db:
            db.execute("INSERT INTO building_dimensions(object_id,width,height,equipment_level) VALUES(?,?,?,?)",
                       (res["object_id"], 2, 2, 3))
            self.assertEqual(quality.owner_grade(db, "?", "alice", 0), 5)
        self.now += DAY + 5
        game_server.wallet("alice")
        row = self.sql("SELECT price, supply, demand FROM market_prices WHERE product='honey' AND month_index=0")[0]
        bare = economy.price_for("honey", row[1], row[2])
        self.assertEqual(row[0], int(round(bare * quality.price_factor(5))))
        self.assertNotEqual(row[0], bare)
        self.books()

    def test_stone_and_gas_make_cement(self):
        with game_server.connect() as db:
            deposits.ensure(db, "?")
            stone = deposits.open_origins(db, "?", "stone")
            gas = deposits.open_origins(db, "?", "gas")
        sx, sy = stone[0][0], stone[0][1]
        region = regions.region_of(sx, sy)
        gx, gy = next((x, y) for x, y, _dep in gas if regions.region_of(x, y) == region)
        for kind, x, y in (("stone_pit", sx, sy), ("gas_well", gx, gy)):
            status, res = game_server.build("alice", {"kind": kind, "x": x, "y": y, "request_id": rid()})
            self.assertEqual(status, 201, res)
        placed = False
        for i in range(25):
            status, res = game_server.build("alice", {"kind": "cement_plant", "x": sx + 4, "y": sy + 4 * i, "request_id": rid()})
            if status == 201:
                placed = True
                break
            if status == 402:
                break
        self.assertTrue(placed, res)
        self.now += DAY + 5
        game_server.wallet("alice")
        cement = self.sql("SELECT supply FROM market_prices WHERE product='cement' AND month_index=0")
        self.assertTrue(cement and cement[0][0] > 0, cement)
        self.books()

    def test_fine_grain_raises_the_flour_price_and_the_books_balance(self):
        status, field = game_server.build("alice", {"kind": "grain_field", "x": 8, "y": 40, "request_id": rid()})
        self.assertEqual(status, 201, field)
        status, mill = game_server.build("alice", {"kind": "mill", "x": 8, "y": 44, "request_id": rid()})
        self.assertEqual(status, 201, mill)
        with game_server.connect() as db:
            db.execute("INSERT INTO building_dimensions(object_id,width,height,equipment_level) VALUES(?,?,?,?)",
                       (field["object_id"], 3, 2, 3))
        self.now += DAY + 5
        game_server.wallet("alice")
        row = self.sql("SELECT price, supply, demand FROM market_prices WHERE product='flour' AND month_index=0")
        self.assertTrue(row and row[0][1] > 0, row)
        bare = economy.price_for("flour", row[0][1], row[0][2])
        self.assertEqual(row[0][0], int(round(bare * quality.price_factor(4))))
        self.books()

    def test_npc_extractor_stands_on_a_deposit_and_passes_zoning(self):
        os.environ["LUNEX_BAL_NPC_NEW_KINDS"] = "1"
        balance.reload()

        def _reset_npc_flag():
            os.environ.pop("LUNEX_BAL_NPC_NEW_KINDS", None)
            balance.reload()

        self.addCleanup(_reset_npc_flag)
        with game_server.connect() as db:
            deposits.ensure(db, "?")
        placed = npc._place_on_deposit("npc:ural-agro", 3, "stone_pit", game_server.build, game_server.connect, "?")
        self.assertTrue(placed)
        with game_server.connect() as db:
            row = db.execute("SELECT id FROM buildings WHERE owner=? AND kind='stone_pit'", ("npc:ural-agro",)).fetchone()
            self.assertIsNotNone(row)
            cells = db.execute("SELECT x,y FROM cells WHERE object_id=?", (row[0],)).fetchall()
            self.assertIsNone(zoning.check(db, "?", "stone_pit", [(int(x), int(y)) for x, y in cells]))
            link = db.execute("SELECT resource FROM building_deposits WHERE object_id=?", (row[0],)).fetchone()
        self.assertEqual(link[0], "stone")
        self.books()

    def _build(self, kind):
        resource = goods_catalog.deposit_resource(kind)
        if resource:
            with game_server.connect() as db:
                origins = deposits.open_origins(db, "?", resource)
            for x, y, _dep in origins[:15]:
                status, _res = game_server.build("alice", {"kind": kind, "x": x, "y": y, "request_id": rid()})
                if status == 201:
                    return True
            return False
        for i in range(30):
            status, _res = game_server.build("alice", {"kind": kind, "x": 20, "y": 30 + 5 * i, "request_id": rid()})
            if status == 201:
                return True
            if status == 402:
                return False
        return False


class NpcKindTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("LUNEX_BAL_NPC_NEW_KINDS", None)
        balance.reload()

    def test_new_kinds_stay_off_until_the_flag_and_then_respect_deposits(self):
        quotes = {p: {"price": 1, "price_if_added": 1, "supply": 50} for p in ("honey", "oil", "goods")}
        persona = {"owner": "npc:test", "name": "T", "pace": 1.0, "focus": {"farm": 3.0, "mine": 1.0, "factory": 1.0}}
        wallet = {"balance": 5_000_000, "holdings": {}}
        self.assertEqual(balance.get("NPC_NEW_KINDS"), 0)
        self.assertIsNone(npc.choose_kind(persona, wallet, quotes))
        os.environ["LUNEX_BAL_NPC_NEW_KINDS"] = "1"
        balance.reload()
        kind = npc.choose_kind(persona, wallet, quotes)
        self.assertTrue(goods_catalog.deposit_resource(kind), kind)
        self.assertIn(kind, economy.BUILD_COST)


if __name__ == "__main__":
    unittest.main()
