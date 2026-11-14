import os
import tempfile
import unittest
import uuid
from unittest import mock

import economy
import game_server
import production

DAY = 86400
T0 = 1_800_000_000


def rid():
    return str(uuid.uuid4())


class ChainBase(unittest.TestCase):
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

    def build(self, who, kind, x=None, y=None):
        """Build on the next free valid site (x/y are ignored: test sites are picked so they are not water)."""
        for _ in range(400):
            self._cursor = getattr(self, "_cursor", 0) + 1
            status, res = game_server.build(who, {"kind": kind, "x": 8, "y": 10 + 7 * self._cursor, "request_id": rid()})
            if status == 201:
                return res
            self.assertIn(res.get("error"), ("water", "road_overlap", "occupied", "no_road_access"), res)
        self.fail("no free site found")

    def month(self, who, n=1):
        self.now += DAY * n + 5
        return game_server.wallet(who)[1]

    def prices(self, month):
        with game_server.connect() as db:
            return {p: pr for p, pr in db.execute("SELECT product,price FROM market_prices WHERE month_index=?", (month,))}

    def assert_ledger_balanced(self):
        with game_server.connect() as db:
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
            negative = db.execute("SELECT 1 FROM wallets WHERE account LIKE 'player:%' AND balance<0").fetchall()
        self.assertEqual((bad, total, negative), ([], 0, []))


class ConfigTests(unittest.TestCase):
    def test_clearing_order_puts_raw_materials_first(self):
        order = production.product_order()
        self.assertEqual(order[-1], "goods")
        self.assertEqual(set(order), {"honey", "oil", "goods"})

    def test_warehouse_has_capacity_and_no_product(self):
        w = economy.PRODUCTION["warehouse"]
        self.assertIsNone(w["product"])
        self.assertEqual(w["capacity"], 400)
        self.assertEqual(economy.BUILD_COST["warehouse"], 80_000)

    def test_server_knows_warehouse_footprint(self):
        self.assertEqual(game_server.KINDS["warehouse"], (3, 3))


class FactoryChainTests(ChainBase):
    def test_factory_without_any_supplier_in_the_world_idles(self):
        self.build("alice", "factory", 8, 10)
        r = self.month("alice")["reports"][0]
        self.assertEqual((r["revenue"], r["input_cost"]), (0, 0))   # nobody sells oil/honey: nothing to buy
        self.assertEqual(r["upkeep"], 56_000)

    def test_factory_buys_inputs_and_sells_goods(self):
        self.build("alice", "factory", 8, 10)
        self.build("bob", "farm", 8, 30)       # other players supply the raw materials
        self.build("carol", "mine", 8, 50)
        w = self.month("alice")
        r = w["reports"][0]
        self.assertGreater(r["revenue"], 0)
        self.assertGreater(r["input_cost"], 0)            # no own farm/mine: everything is bought
        self.assertEqual(r["profit"], r["revenue"] - r["input_cost"] - r["upkeep"])
        self.assert_ledger_balanced()

    def test_own_suppliers_supply_factory_without_market_purchase(self):
        for kind, y in (("farm", 10), ("mine", 30), ("factory", 50)):
            self.build("alice", kind, 8, y)
        r = self.month("alice")["reports"][0]
        self.assertEqual(r["input_cost"], 0)               # inputs came from own stock
        self.assertEqual(r["buildings"], 3)
        self.assert_ledger_balanced()

    def test_integrated_producer_sells_less_raw_than_it_makes(self):
        for kind, y in (("farm", 10), ("mine", 30), ("factory", 50)):
            self.build("alice", kind, 8, y)
        self.month("alice")
        with game_server.connect() as db:
            honey_supply, oil_supply = (db.execute("SELECT supply FROM market_prices WHERE product=? AND month_index=0", (p,)).fetchone()[0] for p in ("honey", "oil"))
        self.assertEqual(honey_supply, 100 - 20)           # 20 honey and
        self.assertEqual(oil_supply, 40 - 10)              # 10 oil went into the factory

    def test_factory_competes_for_scarce_inputs_and_is_rationed(self):
        # Factory + one farm owned by someone else; oil is scarce (no mine at all) -> output collapses to what oil allows.
        self.build("alice", "factory", 8, 10)
        self.build("bob", "farm", 8, 30)
        self.month("alice")
        with game_server.connect() as db:
            goods_supply = db.execute("SELECT supply FROM market_prices WHERE product='goods' AND month_index=0").fetchone()[0]
            oil_supply = db.execute("SELECT supply FROM market_prices WHERE product='oil' AND month_index=0").fetchone()[0]
        self.assertEqual(oil_supply, 0)
        self.assertEqual(goods_supply, 0)                  # no oil at all: the factory cannot produce

    def test_forecast_includes_input_costs(self):
        self.build("alice", "factory", 8, 10)
        w = game_server.wallet("alice")[1]
        f, q = w["forecast"], w["market"]
        self.assertEqual(f["input_cost"], 10 * q["oil"]["price"] + 20 * q["honey"]["price"])
        self.assertEqual(f["profit"], 60 * q["goods"]["price"] - f["input_cost"] - 56_000)

    def test_all_players_see_one_price_for_goods(self):
        self.build("alice", "factory", 8, 10)
        self.build("bob", "farm", 8, 30)
        self.build("carol", "mine", 8, 50)
        self.month("alice", 2)
        self.assertEqual(len(self.prices(0)), 3)
        self.assert_ledger_balanced()


class HoldShareTests(unittest.TestCase):
    """Warehouses react proportionally to the fall of the smoothed price instead of switching all at once."""

    def share(self, prices):
        ref = economy.MARKET["honey"]["reference_price"]

        class Fake:
            def execute(self, sql, params):
                month = params[1]
                value = prices.get(month)
                return type("R", (), {"fetchone": lambda self_: None if value is None else (value,)})()
        # month 10 asks for prices of months 9, 8, 7 (HOLD_SMOOTH_MONTHS)
        return production._hold_share(Fake(), "?", "honey", 10, ref), ref

    def test_no_history_or_price_above_threshold_holds_nothing(self):
        self.assertEqual(self.share({})[0], 0.0)
        ref = economy.MARKET["honey"]["reference_price"]
        self.assertEqual(self.share({9: ref, 8: ref, 7: ref})[0], 0.0)

    def test_share_grows_with_the_depth_of_the_fall_and_is_capped(self):
        ref = economy.MARKET["honey"]["reference_price"]
        mild = self.share({9: int(ref * 0.85), 8: int(ref * 0.85), 7: int(ref * 0.85)})[0]
        deep = self.share({9: int(ref * 0.6), 8: int(ref * 0.6), 7: int(ref * 0.6)})[0]
        floor = self.share({9: int(ref * 0.3), 8: int(ref * 0.3), 7: int(ref * 0.3)})[0]
        self.assertTrue(0.0 < mild < deep <= 1.0)
        self.assertEqual(floor, 1.0)

    def test_one_bad_month_does_not_flip_the_warehouse(self):
        ref = economy.MARKET["honey"]["reference_price"]
        spike = self.share({9: int(ref * 0.5), 8: ref, 7: ref})[0]       # smoothed: a single dip is a partial hold at most
        full = self.share({9: int(ref * 0.5), 8: int(ref * 0.5), 7: int(ref * 0.5)})[0]
        self.assertLess(spike, full)


class WarehouseTests(ChainBase):
    def cheap_honey(self):
        """Force a low honey price: many farms from other players flood the market."""
        for i in range(5):
            self.build("rival%d" % i, "farm", 8, 70 + i * 20)

    def test_without_warehouse_everything_is_sold(self):
        self.build("alice", "farm", 8, 10)
        self.month("alice", 2)
        self.assertEqual(game_server.wallet("alice")[1]["inventory"]["items"], [])

    def test_warehouse_holds_production_when_price_is_low(self):
        self.build("alice", "farm", 8, 10)
        self.build("alice", "warehouse", 8, 30)
        self.cheap_honey()
        w = self.month("alice", 3)    # month 0 sets a low price; later months hold
        inv = w["inventory"]
        self.assertEqual(inv["capacity"], 400)
        self.assertGreater(inv["used"], 0)
        self.assertLessEqual(inv["used"], inv["capacity"])
        self.assert_ledger_balanced()

    def test_stock_never_exceeds_capacity(self):
        self.build("alice", "farm", 8, 10)
        self.build("alice", "farm", 8, 30)
        self.build("alice", "warehouse", 8, 50)
        self.cheap_honey()
        w = self.month("alice", 12)
        self.assertLessEqual(w["inventory"]["used"], 400)

    def test_warehouse_releases_stock_when_price_recovers(self):
        self.build("alice", "farm", 8, 10)
        self.build("alice", "warehouse", 8, 30)
        self.cheap_honey()
        held = self.month("alice", 3)["inventory"]["used"]
        self.assertGreater(held, 0)
        with game_server.connect() as db:
            db.execute("DELETE FROM building_ops WHERE owner LIKE 'rival%'")   # competitors disappear: price recovers
        released = self.month("alice", 3)["inventory"]["used"]
        self.assertLess(released, held)                                         # stock is sold off when the price is good
        self.assert_ledger_balanced()

    def test_stock_is_released_gradually_not_dumped_at_once(self):
        self.build("alice", "farm", 8, 10)
        self.build("alice", "warehouse", 8, 30)
        with game_server.connect() as db:
            db.execute("INSERT INTO inventory(owner,product,qty) VALUES('alice','honey',300) ON CONFLICT(owner,product) DO UPDATE SET qty=300")
        used = self.month("alice", 1)["inventory"]["used"]
        self.assertGreater(used, 0)          # the price is at the reference: part of the stock is still in the warehouse
        self.assertLess(used, 300)           # ... but part of it was sold
        self.assert_ledger_balanced()

    def test_warehouse_sells_instead_of_holding_when_cash_is_short(self):
        self.build("alice", "farm", 8, 10)
        self.build("alice", "warehouse", 8, 30)
        self.cheap_honey()
        with game_server.connect() as db:
            db.execute("UPDATE wallets SET balance=5000 WHERE account='player:alice'")
        w = self.month("alice", 3)
        self.assertEqual(w["inventory"]["used"], 0)         # no runway for costs: production is sold, not stored
        self.assertGreaterEqual(w["balance"], 0)

    def test_warehouse_costs_upkeep(self):
        self.build("alice", "warehouse", 8, 10)
        w = game_server.wallet("alice")[1]
        self.assertEqual(w["forecast"]["upkeep"], 5_000)
        self.assertEqual(w["forecast"]["profit"], -5_000)
        r = self.month("alice")["reports"][0]
        self.assertEqual(r["upkeep"], 5_000)
        self.assertEqual(r["revenue"], 0)

    def test_stock_is_per_owner(self):
        self.build("alice", "farm", 8, 10)
        self.build("alice", "warehouse", 8, 30)
        self.cheap_honey()
        self.month("alice", 3)
        self.assertEqual(game_server.wallet("rival0")[1]["inventory"]["used"], 0)


class EngineSafetyTests(ChainBase):
    def test_processing_is_idempotent(self):
        self.build("alice", "farm", 8, 10)
        self.now += DAY * 3 + 5
        a = game_server.wallet("alice")[1]
        b = game_server.wallet("alice")[1]
        self.assertEqual(a["balance"], b["balance"])
        self.assertEqual(len(a["reports"]), 3)

    def test_catch_up_is_in_order_and_complete(self):
        self.build("alice", "farm", 8, 10)
        self.now += DAY * 8 + 5
        w = game_server.wallet("alice")[1]
        self.assertEqual(sorted(r["month_index"] for r in w["reports"]), [2, 3, 4, 5, 6, 7])  # newest 6 of months 0..7
        with game_server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM market_prices WHERE product='honey'").fetchone()[0], 8)

    def test_unaffordable_costs_do_not_create_debt(self):
        self.build("alice", "factory", 8, 10)
        with game_server.connect() as db:
            db.execute("UPDATE wallets SET balance=1000 WHERE account='player:alice'")
        w = self.month("alice", 2)
        self.assertGreaterEqual(w["balance"], 0)


if __name__ == "__main__":
    unittest.main()
