import os
from construction_test_fixtures import fast_construction
import tempfile
import unittest
import uuid
from unittest import mock

import economy
import game_server

DAY = 86400
T0 = 1_800_000_000


def rid():
    return str(uuid.uuid4())


class PricingMathTests(unittest.TestCase):
    def test_reference_price_when_supply_equals_demand(self):
        for product, m in economy.MARKET.items():
            self.assertEqual(economy.price_for(product, 100, 100), m["reference_price"])

    def test_price_falls_with_oversupply_and_rises_with_scarcity(self):
        ref = economy.MARKET["honey"]["reference_price"]
        self.assertLess(economy.price_for("honey", 300, 200), ref)
        self.assertGreater(economy.price_for("honey", 100, 200), ref)
        self.assertLess(economy.price_for("honey", 400, 200), economy.price_for("honey", 300, 200))

    def test_price_is_clamped(self):
        ref = economy.MARKET["oil"]["reference_price"]
        self.assertEqual(economy.price_for("oil", 0, 80), int(round(ref * economy.MAX_PRICE_K)))
        self.assertEqual(economy.price_for("oil", 10**9, 80), int(round(ref * economy.MIN_PRICE_K)))

    def test_seasonal_demand_and_population_scale(self):
        self.assertGreater(economy.demand_for("honey", 0), economy.demand_for("honey", 5))   # winter vs summer
        self.assertGreater(economy.demand_for("honey", 0, 2.0), economy.demand_for("honey", 0))  # bigger/richer city buys more

    def test_one_building_gets_premium_two_get_reference_price_in_neutral_season(self):
        demand = economy.MARKET["honey"]["base_demand"]
        one = economy.price_for("honey", 100, demand)
        two = economy.price_for("honey", 200, demand)
        self.assertEqual(two, economy.MARKET["honey"]["reference_price"])
        self.assertGreater(one, two)

    def test_every_kind_has_a_market(self):
        for kind, spec in economy.PRODUCTION.items():
            if spec["product"]:
                self.assertIn(spec["product"], economy.MARKET)
            for raw in spec.get("inputs", {}):
                self.assertIn(raw, economy.MARKET)


class MarketIntegrationTests(unittest.TestCase):
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

    def build(self, who, kind, x, y):
        return game_server.build(who, {"kind": kind, "x": x, "y": y, "request_id": rid()})

    def products(self):
        return game_server.market_state()[1]["products"]

    def test_quote_without_buildings(self):
        honey = self.products()["honey"]
        self.assertEqual(honey["supply"], 0)
        self.assertEqual(honey["price"], int(round(200 * economy.MAX_PRICE_K)))
        self.assertGreater(honey["demand"], 0)
        self.assertLess(honey["price_if_added"], honey["price"])

    @fast_construction

    def test_more_farms_lower_the_price(self):
        before = self.products()["honey"]["price"]
        self.build("alice", "farm", 8, 10)
        one = self.products()["honey"]
        self.build("bob", "farm", 8, 30)
        two = self.products()["honey"]
        self.assertEqual((one["supply"], two["supply"]), (100, 200))
        self.assertLess(one["price"], before)
        self.assertLess(two["price"], one["price"])

    @fast_construction

    def test_all_players_get_the_same_stored_price(self):
        self.build("alice", "farm", 8, 10)
        self.build("bob", "farm", 8, 30)
        self.now += DAY + 5
        a = game_server.wallet("alice")[1]
        b = game_server.wallet("bob")[1]
        self.assertEqual(a["reports"][0]["revenue"], b["reports"][0]["revenue"])
        with game_server.connect() as db:
            rows = db.execute("SELECT product,month_index,price,supply FROM market_prices WHERE product='honey'").fetchall()
        self.assertEqual(len(rows), 1)                      # computed once for month 0
        self.assertEqual(rows[0][3], 200)                   # both farms counted
        self.assertEqual(a["reports"][0]["revenue"], 100 * rows[0][2])

    def test_price_is_frozen_once_stored(self):
        self.build("alice", "farm", 8, 10)
        self.now += DAY + 5
        game_server.wallet("alice")
        with game_server.connect() as db:
            stored = db.execute("SELECT price FROM market_prices WHERE product='honey' AND month_index=0").fetchone()[0]
        self.build("bob", "farm", 8, 30)       # a later competitor must not change month 0
        self.now += DAY
        game_server.wallet("bob")
        with game_server.connect() as db:
            again = db.execute("SELECT price FROM market_prices WHERE product='honey' AND month_index=0").fetchone()[0]
        self.assertEqual(stored, again)

    @fast_construction

    def test_wallet_contains_market_and_forecast_uses_it(self):
        self.build("alice", "farm", 8, 10)
        w = game_server.wallet("alice")[1]
        price = w["market"]["honey"]["price"]
        self.assertEqual(w["forecast"]["revenue"], 100 * price)
        self.assertEqual(w["forecast"]["profit"], 100 * price - 8000)

    def test_ledger_balanced_with_market_prices(self):
        self.build("alice", "farm", 8, 10)
        self.build("bob", "mine", 8, 30)
        self.now += DAY * 4 + 5
        game_server.wallet("alice")
        game_server.wallet("bob")
        with game_server.connect() as db:
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
        self.assertEqual((bad, total), ([], 0))


if __name__ == "__main__":
    unittest.main()