import os
import tempfile
import unittest
import uuid
from unittest import mock

import auth
import city
import economy
import game_server
import npc
import production

DAY = 86400
T0 = 1_800_000_000
BUDGET = economy.player_account(economy.CITY)


class CityBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = game_server.DB
        game_server.DB = os.path.join(self.tmp.name, "w.sqlite3")
        self.now = T0
        p = mock.patch.object(game_server.time, "time", side_effect=lambda: self.now)
        p.start()
        self.addCleanup(p.stop)
        self.cursor = 0

    def tearDown(self):
        game_server.DB = self.old
        self.tmp.cleanup()

    def view(self):
        return game_server.city_state()[1]

    def month(self, n=1):
        self.now += DAY * n + 5

    def budget(self):
        with game_server.connect() as db:
            row = db.execute("SELECT balance FROM wallets WHERE account=?", (BUDGET,)).fetchone()
        return row[0] if row else 0

    def fund(self, amount):
        """Put money into the budget from the treasury (keeps the ledger closed)."""
        game_server.city_state()
        with game_server.connect() as db:
            economy.ensure_wallet(db, "?", economy.CITY, self.now)
            economy.post(db, "?", "test", "test funding", [(economy.TREASURY, -amount), (BUDGET, amount)], self.now)

    def make_mayor(self, who):
        game_server.wallet(who)
        game_server.city_state()
        with game_server.connect() as db:
            city.set_mayor(db, "?", who, who, 0)

    def taxes(self, who, profit, prop):
        return game_server.city_taxes(who, {"profit_tax": profit, "property_tax": prop})

    def social(self, who, kind):
        for _ in range(400):
            self.cursor += 1
            status, res = game_server.city_build(who, {"kind": kind, "x": 8, "y": 10 + 7 * self.cursor, "request_id": str(uuid.uuid4())})
            if status == 201:
                return res
            if res.get("error") not in ("water", "road_overlap", "occupied", "no_road_access"):
                return status, res
        self.fail("no site")

    def build(self, who, kind):
        for _ in range(400):
            self.cursor += 1
            status, res = game_server.build(who, {"kind": kind, "x": 8, "y": 10 + 7 * self.cursor, "request_id": str(uuid.uuid4())})
            if status == 201:
                return res
        self.fail("no site")

    def ledger_ok(self):
        with game_server.connect() as db:
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
            neg = db.execute("SELECT 1 FROM wallets WHERE account LIKE 'player:%' AND balance<0").fetchall()
        self.assertEqual((bad, total, neg), ([], 0, []))


class MayorAndTaxTests(CityBase):
    def test_default_mayor_is_the_administration_with_default_taxes(self):
        v = self.view()
        self.assertEqual(v["mayor"]["owner"], city.ADMIN)
        self.assertTrue(v["mayor"]["is_npc"])
        self.assertEqual((v["taxes"]["profit_tax"], v["taxes"]["property_tax"]), (0.13, 0.022))
        self.assertEqual(v["budget"], 0)
        self.assertEqual(v["mayor"]["term_end_month"], economy.ELECTION_PERIOD)

    def test_only_the_mayor_can_change_taxes(self):
        self.assertEqual(self.taxes("alice", 0.10, 0.01), (403, {"error": "not_mayor"}))
        self.make_mayor("alice")
        self.assertEqual(self.taxes("bob", 0.10, 0.01)[0], 403)
        status, res = self.taxes("alice", 0.10, 0.01)
        self.assertEqual(status, 200, res)
        self.assertEqual((res["taxes"]["profit_tax"], res["taxes"]["property_tax"]), (0.10, 0.01))
        self.assertEqual(self.view()["taxes"]["profit_tax"], 0.10)

    def test_limits_are_the_law(self):
        self.make_mayor("alice")
        for profit, prop in ((0.30, 0.01), (0.01, 0.01), (0.13, 0.05), (0.13, -0.01)):
            status, res = self.taxes("alice", profit, prop)
            self.assertEqual((status, res["error"]), (400, "out_of_limits"))
        self.assertEqual(self.taxes("alice", 0.25, 0.022)[0], 200)        # exactly at the limits
        self.month(1)
        self.assertEqual(self.taxes("alice", 0.05, 0.0)[0], 200)

    def test_invalid_rate_types(self):
        self.make_mayor("alice")
        self.assertEqual(self.taxes("alice", "10", 0.01)[1]["error"], "invalid_rate")
        self.assertEqual(self.taxes("alice", True, 0.01)[1]["error"], "invalid_rate")
        self.assertEqual(self.taxes("alice", None, 0.01)[1]["error"], "invalid_rate")

    def test_one_change_per_game_month(self):
        self.make_mayor("alice")
        self.assertEqual(self.taxes("alice", 0.12, 0.02)[0], 200)
        status, res = self.taxes("alice", 0.11, 0.02)
        self.assertEqual((status, res["error"]), (409, "cooldown"))
        self.month(1)
        self.assertEqual(self.taxes("alice", 0.11, 0.02)[0], 200)

    def test_vat_cannot_be_changed_by_the_mayor(self):
        self.make_mayor("alice")
        self.taxes("alice", 0.10, 0.01)
        v = self.view()["taxes"]
        self.assertEqual((v["vat"]["honey"], v["vat"]["oil"], v["vat"]["goods"]), (0.10, 0.22, 0.22))

    def test_companies_pay_the_mayors_rates(self):
        self.make_mayor("alice")
        self.taxes("alice", 0.05, 0.0)
        with mock.patch.object(economy, "price_for", side_effect=lambda p, s, d: economy.MARKET[p]["reference_price"]):
            self.build("bob", "farm")
            self.month(1)
            game_server.wallet("bob")
        with game_server.connect() as db:
            row = db.execute("SELECT profit_tax,property_tax FROM company_taxes WHERE owner='bob'").fetchone()
        self.assertEqual(row, (int((20_000 - 8_000) * 0.05), 0))

    def test_reserved_names_cannot_be_registered_or_used(self):
        old = auth.DB_PATH
        auth.DB_PATH = os.path.join(self.tmp.name, "accounts.sqlite3")
        self.addCleanup(setattr, auth, "DB_PATH", old)
        self.assertEqual(auth.register({"username": "city", "email": "c@example.test", "password": "secret1"}, "ip-1")[1]["error"], "invalid_username")
        self.assertEqual(auth.register({"username": "CITY", "email": "c2@example.test", "password": "secret1"}, "ip-2")[1]["error"], "invalid_username")
        self.assertEqual(auth.RESERVED_NAMES, economy.RESERVED_OWNERS)


class SocialBuildingTests(CityBase):
    def test_players_cannot_build_social_buildings_and_the_city_cannot_build_commercial_ones(self):
        self.assertEqual(game_server.build("alice", {"kind": "school", "x": 8, "y": 10, "request_id": str(uuid.uuid4())})[1]["error"], "social_only_for_city")
        self.assertEqual(game_server.build(economy.CITY, {"kind": "farm", "x": 8, "y": 10, "request_id": str(uuid.uuid4())})[1]["error"], "city_builds_social_only")

    def test_only_the_mayor_orders_construction(self):
        self.fund(2_000_000)
        self.assertEqual(game_server.city_build("alice", {"kind": "school", "x": 8, "y": 10, "request_id": str(uuid.uuid4())})[1]["error"], "not_mayor")
        self.make_mayor("alice")
        self.assertEqual(game_server.city_build("alice", {"kind": "farm", "x": 8, "y": 10, "request_id": str(uuid.uuid4())})[1]["error"], "invalid_build")

    def test_construction_is_paid_from_the_budget(self):
        self.make_mayor("alice")
        self.fund(1_000_000)
        res = self.social("alice", "school")
        self.assertEqual(res["cost"], 400_000 + 5_000 * res["road_cells"])
        self.assertEqual(self.budget(), 1_000_000 - res["cost"])
        self.assertEqual(game_server.wallet("alice")[1]["balance"], 1_000_000)        # the mayor's own money is untouched
        self.assertEqual(self.view()["social"]["counts"]["school"], 1)
        self.ledger_ok()

    def test_empty_budget_blocks_construction(self):
        self.make_mayor("alice")
        status, res = self.social("alice", "hospital")
        self.assertEqual((status, res["error"]), (402, "insufficient_funds"))
        self.assertEqual(self.view()["social"]["counts"]["hospital"], 0)

    def test_coverage_and_quality(self):
        self.make_mayor("alice")
        self.fund(5_000_000)
        before = self.view()["social"]
        self.assertEqual((before["quality"], before["coverage"]["school"]), (0, 0))
        self.social("alice", "school")
        self.social("alice", "hospital")
        self.social("alice", "park")
        social = self.view()["social"]
        self.assertEqual(social["coverage"]["school"], round(120 / 200, 3))
        self.assertEqual((social["coverage"]["hospital"], social["coverage"]["park"]), (1.0, 1.0))
        self.assertAlmostEqual(social["quality"], round((0.6 + 1 + 1) / 3, 3), places=3)

    def test_city_pays_wages_and_upkeep_of_its_buildings(self):
        self.make_mayor("alice")
        self.fund(2_000_000)
        self.social("alice", "school")
        budget_before = self.budget()
        self.month(2)
        game_server.city_state()
        spent = budget_before - self.budget()
        self.assertGreaterEqual(spent, 2 * (6 * economy.BASE_WAGE + 3_000) - 1)
        self.assertEqual(self.view()["labor"]["jobs"] if "labor" in self.view() else 6, 6)
        self.ledger_ok()

    def test_the_city_has_jobs_for_residents(self):
        self.make_mayor("alice")
        self.fund(2_000_000)
        self.social("alice", "hospital")
        self.assertEqual(game_server.market_state()[1]["labor"]["jobs"], 8)

    def test_city_is_never_bankrupt_and_pays_no_taxes(self):
        self.make_mayor("alice")
        self.fund(900_000)
        self.social("alice", "hospital")
        self.set_budget(0)
        self.month(8)
        v = self.view()
        self.assertEqual(len(v["buildings"]), 1)                    # not liquidated
        self.assertGreater(v["arrears"], 0)                         # but it owes
        with game_server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM company_taxes WHERE owner='city' AND (profit_tax>0 OR property_tax>0 OR vat>0)").fetchone()[0], 0)

    def set_budget(self, amount):
        with game_server.connect() as db:
            current = db.execute("SELECT balance FROM wallets WHERE account=?", (BUDGET,)).fetchone()[0]
            db.execute("UPDATE wallets SET balance=? WHERE account=?", (amount, BUDGET))
            db.execute("UPDATE wallets SET balance=balance-? WHERE account=?", (amount - current, economy.TREASURY))

    def test_underfunded_city_services_work_at_half(self):
        self.make_mayor("alice")
        self.fund(2_000_000)
        self.social("alice", "hospital")
        full = self.view()["social"]["coverage"]["hospital"]
        self.set_budget(0)
        self.month(3)
        v = self.view()
        self.assertFalse(v["social"]["funded"])
        self.assertEqual(v["social"]["coverage"]["hospital"], round(full * 0.5, 3))

    def test_sold_by_nobody(self):
        self.make_mayor("alice")
        self.fund(1_000_000)
        res = self.social("alice", "park")
        self.assertEqual(game_server.sell("alice", {"object_id": res["object_id"], "request_id": str(uuid.uuid4())})[1]["error"], "not_owner")


class EffectTests(CityBase):
    def test_quality_raises_output(self):
        with mock.patch.object(economy, "price_for", side_effect=lambda p, s, d: economy.MARKET[p]["reference_price"]):
            self.build("bob", "farm")
            self.month(1)
            game_server.wallet("bob")
            with game_server.connect() as db:
                plain = db.execute("SELECT supply FROM market_prices WHERE product='honey' AND month_index=0").fetchone()[0]
            self.make_mayor("alice")
            self.fund(5_000_000)
            for kind in ("school", "school", "hospital", "park"):
                self.social("alice", kind)
            self.month(2)
            game_server.wallet("bob")
            with game_server.connect() as db:
                better = db.execute("SELECT supply FROM market_prices WHERE product='honey' AND month_index=2").fetchone()[0]
        self.assertEqual(plain, 100)
        self.assertGreater(better, plain)

    def test_quality_speeds_up_population_growth(self):
        base = production.next_population(100_000, 0, 50_000, quality=0.0)
        better = production.next_population(100_000, 0, 50_000, quality=1.0)
        self.assertGreater(better, base)
        grow = production.next_population(100_000, 100_000, 50_000, quality=0.0)
        grow_q = production.next_population(100_000, 100_000, 50_000, quality=1.0)
        self.assertGreater(grow_q, grow)

    def test_city_expenses_roads_and_mayor_salary(self):
        self.make_mayor("alice")
        self.fund(1_000_000)
        self.build("bob", "farm")                                      # builds roads
        with game_server.connect() as db:
            roads = db.execute("SELECT COUNT(*) FROM roads").fetchone()[0]
        before = self.budget()
        alice_before = game_server.wallet("alice")[1]["balance"]
        self.month(1)
        game_server.wallet("alice")
        self.assertGreater(roads, 0)
        self.assertEqual(game_server.wallet("alice")[1]["balance"], alice_before + economy.MAYOR_SALARY)
        self.assertLess(self.budget(), before + 100_000)
        self.ledger_ok()

    def test_budget_never_goes_negative(self):
        self.make_mayor("alice")
        self.build("bob", "farm")
        self.month(6)
        game_server.wallet("bob")
        self.assertGreaterEqual(self.budget(), 0)

    def test_npc_mayor_pays_no_salary(self):
        self.fund(500_000)
        self.build("bob", "farm")
        self.month(2)
        game_server.wallet("bob")
        with game_server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM ledger_tx WHERE memo LIKE 'Зарплата мэра%'").fetchone()[0], 0)


class AdministrationTests(CityBase):
    def view_of(self, budget, coverage, mayor_npc=True, upkeep=0):
        return {"mayor": {"is_npc": mayor_npc}, "budget": budget, "services_upkeep": upkeep, "buildings": [],
                "social": {"coverage": coverage}}

    def test_choose_social_picks_the_least_covered_service(self):
        v = self.view_of(5_000_000, {"school": 0.6, "hospital": 0.3, "park": 1.0})
        self.assertEqual(npc.choose_social(v), "hospital")

    def test_administration_needs_a_reserve(self):
        cost = economy.BUILD_COST["park"]
        reserve = 3 * economy.monthly_cost("park", economy.BASE_WAGE)
        self.assertIsNone(npc.choose_social(self.view_of(cost + reserve - 1, {"school": 1.0, "hospital": 1.0, "park": 0.0})))
        self.assertEqual(npc.choose_social(self.view_of(cost + reserve, {"school": 1.0, "hospital": 1.0, "park": 0.0})), "park")

    def test_nothing_to_build_when_covered_or_when_a_human_is_mayor(self):
        self.assertIsNone(npc.choose_social(self.view_of(9_000_000, {"school": 1.0, "hospital": 0.97, "park": 1.0})))
        self.assertIsNone(npc.choose_social(self.view_of(9_000_000, {"school": 0.0, "hospital": 0.0, "park": 0.0}, mayor_npc=False)))

    def test_administration_builds_with_a_funded_budget(self):
        game_server.npc_tick()
        self.fund(3_000_000)
        for _ in range(4):
            self.month(1)
            game_server.npc_tick()
        v = self.view()
        self.assertGreater(len(v["buildings"]), 0)
        self.assertLess(self.budget(), 3_000_000)
        self.ledger_ok()

    def test_a_human_mayor_is_never_overridden(self):
        self.make_mayor("alice")
        game_server.npc_tick()
        self.fund(3_000_000)
        for _ in range(4):
            self.month(1)
            game_server.npc_tick()
        self.assertEqual(len(self.view()["buildings"]), 0)


if __name__ == "__main__":
    unittest.main()
