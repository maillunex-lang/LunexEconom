import os
from construction_test_fixtures import fast_construction
import tempfile
import unittest
import uuid
from unittest import mock

import economy
import game_server
import npc

DAY = 86400
T0 = 1_800_000_000


def quotes(honey=200, oil=1500, goods=2000, honey_supply=100, oil_supply=40):
    return {
        "honey": {"price": honey, "price_if_added": honey, "supply": honey_supply, "name": "Мёд"},
        "oil": {"price": oil, "price_if_added": oil, "supply": oil_supply, "name": "Нефть"},
        "goods": {"price": goods, "price_if_added": goods, "supply": 60, "name": "Товары"},
    }


class DecisionTests(unittest.TestCase):
    persona = {"owner": "npc:test", "name": "T", "pace": 1.0, "focus": {"farm": 3.0, "mine": 1.0, "factory": 1.0, "warehouse": 1.0}}

    def test_builds_the_most_profitable_option(self):
        kind = npc.choose_kind(self.persona, {"balance": 1_000_000, "holdings": {}}, quotes())
        self.assertEqual(kind, "farm")                       # highest focus weight, good payback

    def test_stops_when_market_is_saturated(self):
        low = quotes(honey=90, oil=500, goods=800)           # nothing pays back within the limit
        self.assertIsNone(npc.choose_kind(self.persona, {"balance": 1_000_000, "holdings": {}}, low))

    def test_respects_cash_reserve(self):
        cheapest = economy.BUILD_COST["farm"] + economy.ROAD_CELL_COST * npc.ROAD_ESTIMATE_CELLS
        self.assertIsNone(npc.choose_kind(self.persona, {"balance": cheapest + npc.RESERVE - 1, "holdings": {}}, quotes()))
        self.assertEqual(npc.choose_kind(self.persona, {"balance": cheapest + npc.RESERVE, "holdings": {}}, quotes()), "farm")

    def test_factory_needs_raw_suppliers(self):
        only_factory = {"owner": "npc:f", "name": "F", "pace": 1.0, "focus": {"factory": 1.0}}
        self.assertIsNone(npc.choose_kind(only_factory, {"balance": 2_000_000, "holdings": {}}, quotes(oil_supply=0)))
        self.assertIsNone(npc.choose_kind(only_factory, {"balance": 2_000_000, "holdings": {}}, quotes(honey_supply=0)))

    def test_building_cap(self):
        wallet = {"balance": 5_000_000, "holdings": {"farm": npc.MAX_BUILDINGS}}
        self.assertIsNone(npc.choose_kind(self.persona, wallet, quotes()))

    def test_warehouse_only_after_several_producers(self):
        only_wh = {"owner": "npc:w", "name": "W", "pace": 1.0, "focus": {"warehouse": 1.0}}
        self.assertIsNone(npc.choose_kind(only_wh, {"balance": 1_000_000, "holdings": {"farm": 1}}, quotes()))
        self.assertEqual(npc.choose_kind(only_wh, {"balance": 1_000_000, "holdings": {"farm": 2}}, quotes()), "warehouse")
        self.assertIsNone(npc.choose_kind(only_wh, {"balance": 1_000_000, "holdings": {"farm": 2, "warehouse": 1}}, quotes()))

    def test_personas_are_valid(self):
        owners = [p["owner"] for p in npc.PERSONAS]
        self.assertEqual(len(owners), len(set(owners)))
        for p in npc.PERSONAS:
            self.assertTrue(npc.is_npc(p["owner"]))
            self.assertTrue(0 < p["pace"] <= 1)
            for kind in p["focus"]:
                self.assertIn(kind, economy.PRODUCTION)

    def test_pace_gates_actions_deterministically(self):
        slow = dict(self.persona, pace=0.0)
        self.assertIsNone(npc.act(slow, 5, lambda o: self.fail("must not act"), lambda: quotes(), lambda *a: self.fail("no build")))
        self.assertEqual(npc._rand("npc:x", 3, "a"), npc._rand("npc:x", 3, "a"))
        self.assertNotEqual(npc._rand("npc:x", 3, "a"), npc._rand("npc:x", 4, "a"))


class WorldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = game_server.DB
        game_server.DB = os.path.join(self.tmp.name, "w.sqlite3")
        self.now = T0
        p = mock.patch.object(game_server.time, "time", side_effect=lambda: self.now)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        game_server.DB = self.old
        self.tmp.cleanup()

    def run_months(self, n):
        for _ in range(n):
            self.now += DAY + 5
            game_server.npc_tick()

    def npc_buildings(self):
        with game_server.connect() as db:
            return db.execute("SELECT owner,kind,x,y FROM buildings WHERE owner LIKE 'npc:%' ORDER BY owner,x,y,kind").fetchall()

    def test_npcs_start_building_and_pay_for_it(self):
        game_server.npc_tick()            # creates NPC state at the starting month
        self.run_months(8)
        buildings = self.npc_buildings()
        self.assertGreater(len(buildings), 0)
        self.assertLessEqual(len(buildings), len(npc.PERSONAS) * 8)
        for persona in npc.PERSONAS:
            bal = game_server.wallet(persona["owner"])[1]["balance"]
            self.assertGreaterEqual(bal, 0)

    def test_ledger_stays_balanced_with_npcs(self):
        game_server.npc_tick()
        self.run_months(10)
        game_server.market_state()
        with game_server.connect() as db:
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
            negative = db.execute("SELECT 1 FROM wallets WHERE account LIKE 'player:%' AND balance<0").fetchall()
        self.assertEqual((bad, total, negative), ([], 0, []))

    def test_world_is_deterministic(self):
        def simulate(path):
            game_server.DB = path
            self.now = T0
            game_server.npc_tick()
            self.run_months(8)
            return self.npc_buildings()
        a = simulate(os.path.join(self.tmp.name, "a.sqlite3"))
        b = simulate(os.path.join(self.tmp.name, "b.sqlite3"))
        self.assertEqual(a, b)

    def test_tick_is_idempotent_within_a_month(self):
        game_server.npc_tick()
        self.run_months(4)
        before = self.npc_buildings()
        self.assertEqual(game_server.npc_tick(), 0)
        self.assertEqual(self.npc_buildings(), before)

    def test_catch_up_after_long_downtime_is_capped(self):
        game_server.npc_tick()
        self.now += DAY * 60
        game_server.npc_tick()
        self.assertLessEqual(len(self.npc_buildings()), len(npc.PERSONAS) * npc.MAX_CATCH_UP)

    def test_npcs_do_not_flood_a_market_forever(self):
        game_server.npc_tick()
        self.run_months(40)
        status, data = game_server.market_state()
        honey, oil, goods = (data["products"][p] for p in ("honey", "oil", "goods"))
        for q in (honey, oil, goods):
            self.assertGreater(q["price_if_added"], q["reference_price"] * 0.3)    # prices not driven into the floor
        total = sum(c["buildings"] for c in data["competitors"])
        self.assertLessEqual(total, len(npc.PERSONAS) * npc.MAX_BUILDINGS)

    def test_market_lists_competitors(self):
        game_server.npc_tick()
        self.run_months(5)
        data = game_server.market_state()[1]
        self.assertEqual([c["name"] for c in data["competitors"]], [p["name"] for p in npc.PERSONAS])
        self.assertEqual(sum(c["buildings"] for c in data["competitors"]), len(self.npc_buildings()))

    @fast_construction

    def test_players_share_the_market_with_npcs(self):
        game_server.npc_tick()
        self.run_months(6)
        honey_before = game_server.market_state()[1]["products"]["honey"]["supply"]
        status, res = game_server.build("alice", {"kind": "farm", "x": 8, "y": 10, "request_id": str(uuid.uuid4())})
        if status == 201:
            honey_after = game_server.market_state()[1]["products"]["honey"]["supply"]
            self.assertEqual(honey_after, honey_before + 100)

    def test_usernames_cannot_collide_with_npcs(self):
        import re
        for p in npc.PERSONAS:
            self.assertIsNone(re.fullmatch(r"[A-Za-zА-Яа-яЁё0-9_]{3,24}", p["owner"]))


if __name__ == "__main__":
    unittest.main()