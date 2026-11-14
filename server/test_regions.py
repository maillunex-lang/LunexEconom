"""City economies and inter-city trade (docs/CITY_ECONOMY.md)."""
import os
import tempfile
import unittest
import uuid
from unittest import mock

import economy
import game_server
import regions

DAY = 86400
T0 = 1_800_000_000


class RegionMathTests(unittest.TestCase):
    def test_nearest_city_owns_a_cell(self):
        self.assertEqual(regions.region_of(5, 5), "ufa")
        self.assertEqual(regions.region_of(-3, 373), "sterlitamak")

    def test_transit_time_grows_with_distance(self):
        near = regions.transit_months("ufa", "sterlitamak")
        far = regions.transit_months("ufa", "sibay")
        self.assertGreaterEqual(near, 1)
        self.assertGreater(far, near)
        self.assertEqual(regions.transit_months("ufa", "ufa"), 0)
        self.assertEqual(regions.transit_months("ufa", "sibay"), regions.transit_months("sibay", "ufa"))

    def test_transport_cost_grows_with_distance(self):
        self.assertLess(regions.unit_cost("honey", "ufa", "sterlitamak"), regions.unit_cost("honey", "ufa", "sibay"))
        self.assertEqual(regions.unit_cost("honey", "ufa", "ufa"), 0)

    def test_game_city_keeps_legacy_population_and_others_scale_with_size(self):
        self.assertEqual(regions.base_population("ufa"), economy.BASE_POPULATION)
        self.assertLess(regions.base_population("sterlitamak"), economy.BASE_POPULATION)
        self.assertGreaterEqual(regions.base_population("baymak"), regions.MIN_POPULATION_FOR_CITY)

    def test_plan_sends_surplus_to_the_dearer_city_only(self):
        ref = economy.MARKET["honey"]["reference_price"]
        plan = regions.plan_exports("honey", ["ufa", "sterlitamak"], {"ufa": 0, "sterlitamak": 500}, {"ufa": 300, "sterlitamak": 100},
                                    {}, {"ufa": ref * 2, "sterlitamak": ref // 2}, {})
        self.assertTrue(plan and plan[0][:2] == ("sterlitamak", "ufa"))
        self.assertLessEqual(plan[0][2], 400)                  # never more than the surplus
        flat = regions.plan_exports("honey", ["ufa", "sterlitamak"], {"ufa": 0, "sterlitamak": 500}, {"ufa": 300, "sterlitamak": 100},
                                    {}, {"ufa": ref, "sterlitamak": ref}, {})
        self.assertEqual(flat, [])                              # no price gap, no trade

    def test_goods_already_on_the_road_are_not_sent_twice(self):
        ref = economy.MARKET["honey"]["reference_price"]
        plan = regions.plan_exports("honey", ["ufa", "sterlitamak"], {"ufa": 0, "sterlitamak": 500}, {"ufa": 300, "sterlitamak": 100},
                                    {}, {"ufa": ref * 2, "sterlitamak": ref // 2}, {"ufa": 300})
        self.assertEqual(plan, [])


class TwoCityWorldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = game_server.DB
        game_server.DB = os.path.join(self.tmp.name, "w.sqlite3")
        self.now = T0
        p = mock.patch.object(game_server.time, "time", side_effect=lambda: self.now)
        p.start()
        self.addCleanup(p.stop)
        self.cursor = {}

    def tearDown(self):
        game_server.DB = self.old
        self.tmp.cleanup()

    def build(self, who, kind, cx, cy):
        key = (cx, cy)
        for _ in range(400):
            n = self.cursor.get(key, 0)
            self.cursor[key] = n + 1
            status, res = game_server.build(who, {"kind": kind, "x": cx + 9 * (n % 8), "y": cy + 7 * (n // 8), "request_id": str(uuid.uuid4())})
            if status == 201:
                return res
        self.fail("no site")

    def rich(self, who):
        game_server.wallet(who)
        with game_server.connect() as db:
            db.execute("UPDATE wallets SET balance=? WHERE account=?", (50_000_000, economy.player_account(who)))
            db.execute("UPDATE wallets SET balance=balance-? WHERE account=?", (49_000_000, economy.TREASURY))

    def month(self, n=1):
        self.now += DAY * n + 5
        game_server.wallet("alice")

    def shipments(self):
        with game_server.connect() as db:
            return db.execute("SELECT product,origin,destination,qty,depart_month,arrive_month,status FROM trade_shipments ORDER BY depart_month,id").fetchall()

    def test_farms_in_another_city_supply_a_factory_with_a_delay(self):
        self.rich("alice")
        self.rich("bob")
        for _ in range(6):
            self.build("alice", "farm", -3, 380)           # Sterlitamak: honey
        self.build("bob", "mine", 8, 10)                    # Ufa: oil and the factory
        self.build("bob", "factory", 8, 60)
        self.month(8)
        ships = self.shipments()
        self.assertTrue(ships, "honey must travel from the farms' city to the Ufa factory")
        gap = regions.transit_months("sterlitamak", "ufa")
        for product, origin, destination, qty, depart, arrive, status in ships:
            self.assertEqual((origin, destination), ("sterlitamak", "ufa"))
            self.assertEqual(arrive - depart, gap)
            self.assertGreater(qty, 0)
        with game_server.connect() as db:
            imports = db.execute("SELECT COALESCE(SUM(imports),0) FROM market_prices_region WHERE region='ufa' AND product='honey'").fetchone()[0]
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            pops = db.execute("SELECT COUNT(*) FROM region_population WHERE region='sterlitamak'").fetchone()[0]
        self.assertGreater(imports, 0)                      # arrived only after the transit time
        self.assertEqual(bad, [])
        self.assertGreater(pops, 0)                         # the second city has its own labour market

    def test_farther_city_receives_later(self):
        self.assertGreater(regions.transit_months("sibay", "ufa"), regions.transit_months("sterlitamak", "ufa"))

    def test_overview_lists_cities_prices_and_shipments(self):
        self.rich("alice")
        self.rich("bob")
        for _ in range(6):
            self.build("alice", "farm", -3, 380)
        self.build("bob", "mine", 8, 10)
        self.build("bob", "factory", 8, 60)
        self.month(6)
        with game_server.connect() as db:
            view = regions.overview(db, "?")
        ids = [c["id"] for c in view["cities"]]
        self.assertEqual(ids[0], "ufa")
        self.assertIn("sterlitamak", ids)
        self.assertTrue(all("honey" in c["prices"] for c in view["cities"]))
        self.assertTrue(any(l["from"] == "sterlitamak" and l["to"] == "ufa" and l["months"] >= 1 for l in view["lanes"]))

    def test_one_city_world_has_no_shipments(self):
        self.rich("alice")
        for _ in range(3):
            self.build("alice", "farm", 8, 10)
        self.month(4)
        self.assertEqual(self.shipments(), [])
        with game_server.connect() as db:
            rows = db.execute("SELECT DISTINCT region FROM market_prices_region").fetchall()
        self.assertEqual([r[0] for r in rows], ["ufa"])

    def test_contract_between_cities_is_refused(self):
        self.rich("alice")
        self.rich("bob")
        self.build("alice", "farm", -3, 380)
        self.build("bob", "factory", 8, 10)
        self.month(1)
        import contracts
        with game_server.connect() as db:
            self.assertNotEqual(regions.home_region(db, "?", "alice"), regions.home_region(db, "?", "bob"))
            offer = uuid.uuid4().hex
            db.execute("INSERT INTO trade_offers(id,supplier,product,qty,price,term_months,penalty,status,created_month,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (offer, "alice", "honey", 10, 100, 3, 0, "open", 1, self.now))
            status, body = contracts.accept(db, "?", "bob", {"offer_id": offer}, 1, self.now)
        self.assertEqual((status, body.get("error")), (409, "different_city"))


if __name__ == "__main__":
    unittest.main()
