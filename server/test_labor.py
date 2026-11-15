import os
from construction_test_fixtures import fast_construction
import tempfile
import unittest
import uuid
from unittest import mock

import economy
import game_server
import production

DAY = 86400
T0 = 1_800_000_000


class LabourMathTests(unittest.TestCase):
    def test_base_wage_reproduces_old_building_costs(self):
        # maintenance + wages at the base wage equals the old lump-sum upkeep
        for kind, total in {"farm": 8_000, "mine": 30_000, "factory": 56_000, "warehouse": 5_000}.items():
            self.assertEqual(economy.monthly_cost(kind, economy.BASE_WAGE), total)

    def test_full_employment_has_unit_demand_scale(self):
        labor = int(economy.BASE_POPULATION * economy.PARTICIPATION)
        lab = production.labor_market(economy.BASE_POPULATION, labor)
        self.assertEqual(lab["wage"], economy.BASE_WAGE)
        self.assertEqual(lab["staffing"], 1.0)
        self.assertAlmostEqual(lab["scale"], 1.0, places=6)

    def test_unemployment_lowers_demand_but_not_wages(self):
        lab = production.labor_market(economy.BASE_POPULATION, 0)
        self.assertEqual(lab["wage"], economy.BASE_WAGE)               # wages are sticky downwards
        self.assertAlmostEqual(lab["scale"], 1 - economy.INCOME_WEIGHT, places=6)
        self.assertEqual(lab["unemployment"], 1.0)

    def test_labour_shortage_raises_wage_and_limits_staffing(self):
        labor = int(economy.BASE_POPULATION * economy.PARTICIPATION)
        lab = production.labor_market(economy.BASE_POPULATION, labor * 2)
        self.assertEqual(lab["staffing"], 0.5)
        self.assertGreater(lab["wage"], economy.BASE_WAGE)
        self.assertLessEqual(lab["wage"], economy.BASE_WAGE * economy.WAGE_MAX)
        self.assertEqual(production.labor_market(economy.BASE_POPULATION, labor * 50)["wage"], int(economy.BASE_WAGE * economy.WAGE_MAX))

    def test_higher_wages_raise_demand(self):
        labor = int(economy.BASE_POPULATION * economy.PARTICIPATION)
        tight = production.labor_market(economy.BASE_POPULATION, int(labor * 1.3))
        self.assertGreater(tight["scale"], 1.0)

    def test_migration_follows_jobs(self):
        labor = int(economy.BASE_POPULATION * economy.PARTICIPATION)
        big = 100_000                                                    # large city: rounding does not hide the effect
        big_labor = int(big * economy.PARTICIPATION)
        grow = production.next_population(big, big_labor * 2, big_labor)
        shrink = production.next_population(big, 0, big_labor)
        stay = production.next_population(big, big_labor, big_labor)
        self.assertGreater(grow, stay)
        self.assertLess(shrink, stay)
        self.assertGreater(stay, big)                                    # natural growth only
        self.assertGreater(grow, big * (1 + economy.NATURAL_GROWTH))     # immigration on top

    def test_population_has_a_floor(self):
        self.assertEqual(production.next_population(economy.MIN_POPULATION, 0, 100), economy.MIN_POPULATION)

    def test_every_building_has_jobs(self):
        for kind, spec in economy.PRODUCTION.items():
            self.assertGreater(spec["jobs"], 0, kind)


class LabourWorldTests(unittest.TestCase):
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

    def build(self, who, kind):
        for _ in range(400):
            self.cursor += 1
            status, res = game_server.build(who, {"kind": kind, "x": 8 + 9 * (self.cursor % 12), "y": 10 + 7 * (self.cursor // 12), "request_id": str(uuid.uuid4())})
            if status == 201:
                return res
        self.fail("no site")

    def month(self, n=1):
        self.now += DAY * n + 5

    def population_rows(self):
        with game_server.connect() as db:
            return db.execute("SELECT month_index,population,labor_force,jobs,wage,staffing_permille,demand_permille,next_population FROM population ORDER BY month_index").fetchall()

    def test_wallet_and_market_expose_labour(self):
        w = game_server.wallet("alice")[1]
        self.assertEqual(w["labor"]["population"], economy.BASE_POPULATION)
        self.assertEqual(w["labor"]["wage"], economy.BASE_WAGE)
        m = game_server.market_state()[1]
        self.assertIn("labor", m)
        self.assertEqual(m["labor"]["jobs"], 0)

    @fast_construction

    def test_buildings_create_jobs(self):
        self.build("alice", "farm")
        self.build("alice", "mine")
        lab = game_server.wallet("alice")[1]["labor"]
        self.assertEqual(lab["jobs"], 4 + 10)

    @fast_construction

    def test_wages_paid_to_residents_and_ledger_balanced(self):
        # Wages are what residents earn; their spending is switched off here so that the balance shows the earnings alone.
        with unittest.mock.patch.object(economy, "RESIDENT_SPEND_TO_MARKET", False):
            self.build("alice", "farm")
            self.month(2)
            game_server.wallet("alice")
        with game_server.connect() as db:
            residents = db.execute("SELECT balance FROM wallets WHERE account=?", (economy.RESIDENTS,)).fetchone()[0]
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
        self.assertEqual(residents, 2 * 6_000)        # 4 farm workers * 1500 for two months
        self.assertEqual((total, bad), (0, []))

    def test_residents_spend_wages_and_the_money_circle_closes(self):
        self.build("alice", "farm")
        self.month(6)
        game_server.wallet("alice")
        with game_server.connect() as db:
            earned = db.execute("SELECT COALESCE(SUM(e.amount),0) FROM ledger_entries e JOIN ledger_tx t ON t.id=e.tx_id WHERE e.account=? AND t.kind='monthly'", (economy.RESIDENTS,)).fetchone()[0]
            spent = -db.execute("SELECT COALESCE(SUM(e.amount),0) FROM ledger_entries e JOIN ledger_tx t ON t.id=e.tx_id WHERE e.account=? AND t.kind='residents'", (economy.RESIDENTS,)).fetchone()[0]
            residents = db.execute("SELECT balance FROM wallets WHERE account=?", (economy.RESIDENTS,)).fetchone()[0]
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
        self.assertGreater(spent, 0)
        self.assertGreaterEqual(residents, 0)                 # residents never spend more than they earned
        self.assertEqual(earned - spent, residents)
        self.assertEqual(bad, [])

    def test_empty_city_does_not_collapse(self):
        # no jobs at all for years: unemployment erodes the city only slowly and never below the floor
        game_server.wallet("alice")
        self.month(36)
        game_server.wallet("alice")
        rows = self.population_rows()
        self.assertGreaterEqual(min(r[1] for r in rows), economy.MIN_POPULATION)
        self.assertGreater(rows[-1][1], economy.BASE_POPULATION * 0.6)

    def rich(self, who="alice", amount=50_000_000):
        game_server.wallet(who)
        with game_server.connect() as db:
            db.execute("UPDATE wallets SET balance=? WHERE account=?", (amount, economy.player_account(who)))
            db.execute("UPDATE wallets SET balance=balance-? WHERE account=?", (amount - 1_000_000, economy.TREASURY))

    @fast_construction

    def test_labour_shortage_grows_population_and_cuts_output(self):
        self.rich()
        for _ in range(40):
            self.build("alice", "farm")                                     # 160 jobs vs 150 workers
        game_server.wallet("alice")
        self.month(1)
        game_server.wallet("alice")
        month, population, labor, jobs, wage, staffing, scale, next_pop = self.population_rows()[0]
        self.assertGreater(jobs, labor)                                     # jobs > labour force
        self.assertLess(staffing, 1000)                                     # understaffed
        self.assertGreater(wage, economy.BASE_WAGE)                         # wage went up
        self.assertGreater(next_pop, population)                            # immigration
        with game_server.connect() as db:
            supply = db.execute("SELECT supply FROM market_prices WHERE product='honey' AND month_index=0").fetchone()[0]
        self.assertLess(supply, 40 * 100)                                   # output scaled down by staffing
        self.assertAlmostEqual(supply, 40 * 100 * staffing / 1000, delta=40)

    @fast_construction

    def test_wages_rise_with_shortage_so_costs_rise(self):
        self.rich()
        for _ in range(40):
            self.build("alice", "farm")
        lab = game_server.wallet("alice")[1]["labor"]
        f = game_server.wallet("alice")[1]["forecast"]
        self.assertGreater(lab["wage"], economy.BASE_WAGE)
        self.assertAlmostEqual(f["wages"], 40 * 4 * lab["staffing"] * lab["wage"], delta=100)   # per-building rounding

    def test_demand_scale_uses_population(self):
        self.build("alice", "farm")
        self.month(3)
        game_server.wallet("alice")
        rows = self.population_rows()
        self.assertTrue(all(r[6] > 0 for r in rows))
        with game_server.connect() as db:
            demand = db.execute("SELECT demand FROM market_prices WHERE product='honey' AND month_index=0").fetchone()[0]
        expected = economy.demand_for("honey", 0, rows[0][6] / 1000)
        self.assertAlmostEqual(demand, expected, delta=2)

    @fast_construction

    def test_forecast_shows_wages(self):
        self.build("alice", "factory")
        f = game_server.wallet("alice")[1]["forecast"]
        self.assertEqual(f["wages"], 20 * economy.BASE_WAGE)
        self.assertEqual(f["upkeep"], 26_000 + 20 * economy.BASE_WAGE)


if __name__ == "__main__":
    unittest.main()