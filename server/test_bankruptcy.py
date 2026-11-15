import os
from construction_test_fixtures import fast_construction
import tempfile
import unittest
import uuid
from unittest import mock

import economy
import game_server
import npc
import production

DAY = 86400
T0 = 1_800_000_000


class BankruptcyBase(unittest.TestCase):
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
            status, res = game_server.build(who, {"kind": kind, "x": 8, "y": 10 + 7 * self.cursor, "request_id": str(uuid.uuid4())})
            if status == 201:
                return res
        self.fail("no site")

    def month(self, who="alice", n=1):
        self.now += DAY * n + 5
        return game_server.wallet(who)[1]

    def set_cash(self, who, amount):
        """Set a wallet balance directly; the treasury absorbs the difference so the ledger stays closed."""
        game_server.wallet(who)
        account = economy.player_account(who)
        with game_server.connect() as db:
            current = db.execute("SELECT balance FROM wallets WHERE account=?", (account,)).fetchone()[0]
            db.execute("UPDATE wallets SET balance=? WHERE account=?", (amount, account))
            db.execute("UPDATE wallets SET balance=balance-? WHERE account=?", (amount - current, economy.TREASURY))

    def assert_ledger_balanced(self):
        with game_server.connect() as db:
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
            negative = db.execute("SELECT 1 FROM wallets WHERE account LIKE 'player:%' AND balance<0").fetchall()
        self.assertEqual((bad, total, negative), ([], 0, []))

    def idle_factory(self, who="alice", cash=60_000):
        """A factory with no raw-material supplier never earns anything but its wages and maintenance are due."""
        self.build(who, "factory")
        self.set_cash(who, cash)


class ArrearsTests(BankruptcyBase):
    def test_healthy_company_has_no_arrears(self):
        self.build("alice", "farm")
        w = self.month("alice", 5)
        self.assertEqual(w["company"]["missed"], 0)
        self.assertEqual(w["company"]["arrears"], 0)
        self.assertEqual(w["company"]["bankruptcies"], 0)

    def test_unpaid_costs_become_arrears_not_forgiveness(self):
        self.idle_factory(cash=60_000)                 # month cost 56 000, so the second month cannot be paid
        w = self.month("alice", 2)
        self.assertEqual(w["balance"], 0)
        self.assertEqual(w["company"]["missed"], 1)
        self.assertGreater(w["company"]["arrears"], 0)
        self.assertGreater(w["company"]["wages_owed"], 0)

    def test_arrears_are_repaid_from_later_cash_wages_first(self):
        self.idle_factory(cash=60_000)
        self.month("alice", 2)
        before = game_server.wallet("alice")[1]["company"]
        self.set_cash("alice", 20_000)
        after = self.month("alice", 1)["company"]
        self.assertLess(after["wages_owed"], before["wages_owed"] + 30_000)   # cash went to wages, not just maintenance
        self.assert_ledger_balanced()

    def test_missed_counter_resets_after_a_paid_month(self):
        self.idle_factory(cash=60_000)
        self.month("alice", 2)
        self.assertEqual(game_server.wallet("alice")[1]["company"]["missed"], 1)
        self.set_cash("alice", 5_000_000)
        w = self.month("alice", 1)
        self.assertEqual(w["company"]["missed"], 0)
        self.assertEqual(w["company"]["arrears"], 0)           # fully repaid from cash

    @fast_construction

    def test_distress_halves_output(self):
        self.build("alice", "farm")
        self.month("alice", 1)
        with game_server.connect() as db:
            healthy = db.execute("SELECT supply FROM market_prices WHERE product='honey' AND month_index=0").fetchone()[0]
            db.execute("INSERT INTO company_status(owner,missed,wages_owed,input_owed,maint_owed,bankruptcies,last_bankruptcy_month,written_off) VALUES('alice',1,100,0,0,0,NULL,0) ON CONFLICT(owner) DO UPDATE SET missed=1")
        self.month("alice", 1)
        with game_server.connect() as db:
            sick = db.execute("SELECT supply FROM market_prices WHERE product='honey' AND month_index=1").fetchone()[0]
        self.assertEqual(sick, int(healthy * economy.DISTRESS_OUTPUT))


class LiquidationTests(BankruptcyBase):
    def go_bankrupt(self, who="alice", cash=60_000):
        self.idle_factory(who, cash)
        return self.month(who, 5)

    def test_company_is_liquidated_after_three_missed_months(self):
        w = self.go_bankrupt()
        self.assertEqual(w["company"]["bankruptcies"], 1)
        self.assertEqual(w["company"]["missed"], 0)
        self.assertEqual(w["company"]["arrears"], 0)
        self.assertEqual(w["holdings"], {})
        self.assertIsNotNone(w["company"]["last_bankruptcy_month"])

    def test_buildings_leave_the_map_and_clients_are_told(self):
        self.idle_factory()
        with game_server.connect() as db:
            before_cells = db.execute("SELECT COUNT(*) FROM cells").fetchone()[0]
        self.month("alice", 5)
        with game_server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM buildings WHERE owner='alice'").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM cells").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM building_ops").fetchone()[0], 0)
            self.assertGreater(before_cells, 0)
            removed = db.execute("SELECT cx,cy,version,payload FROM events WHERE kind='building_removed'").fetchall()
        self.assertGreater(len(removed), 0)
        status, data = game_server.events(0)
        kinds = [e["kind"] for e in data["events"]]
        self.assertIn("building_removed", kinds)
        # chunk versions stay strictly sequential, otherwise clients would resynchronise forever
        seen = {}
        for e in data["events"]:
            key = (e["cx"], e["cy"])
            self.assertEqual(e["version"], seen.get(key, 0) + 1)
            seen[key] = e["version"]

    def test_assets_are_sold_and_creditors_paid_first(self):
        self.idle_factory(cash=60_000)
        w = self.month("alice", 5)
        proceeds = int(economy.BUILD_COST["factory"] * economy.LIQUIDATION_RATE)
        with game_server.connect() as db:
            tx = db.execute("SELECT memo FROM ledger_tx WHERE kind='liquidation' ORDER BY created, id").fetchall()
        memos = " | ".join(m for (m,) in tx)
        self.assertIn("продажа зданий", memos)
        self.assertGreaterEqual(proceeds, 180_000)
        self.assertGreater(w["balance"], 0)                     # something is left for the owner
        self.assert_ledger_balanced()

    def test_leftover_debt_is_written_off(self):
        # Costs far above the sale value: use a tiny company value so that debt exceeds the proceeds.
        self.build("alice", "warehouse")
        self.set_cash("alice", 0)
        with game_server.connect() as db:
            db.execute("INSERT INTO company_status(owner,missed,wages_owed,input_owed,maint_owed,bankruptcies,last_bankruptcy_month,written_off) VALUES('alice',2,500000,0,0,0,NULL,0) ON CONFLICT(owner) DO UPDATE SET missed=2,wages_owed=500000")
        w = self.month("alice", 1)
        self.assertEqual(w["company"]["bankruptcies"], 1)
        self.assertEqual(w["company"]["arrears"], 0)
        self.assertGreater(w["company"]["written_off"], 0)
        self.assertEqual(w["balance"], 0)                       # everything went to creditors
        self.assert_ledger_balanced()

    def test_inventory_is_sold_on_liquidation(self):
        self.build("alice", "farm")
        self.build("alice", "warehouse")
        self.set_cash("alice", 0)
        with game_server.connect() as db:
            db.execute("INSERT INTO inventory(owner,product,qty) VALUES('alice','honey',300) ON CONFLICT(owner,product) DO UPDATE SET qty=300")
            production.liquidate(db, "?", "alice", 1, 1_800_000_000)
            left = db.execute("SELECT COALESCE(SUM(qty),0) FROM inventory WHERE owner='alice'").fetchone()[0]
            memos = " | ".join(m for (m,) in db.execute("SELECT memo FROM ledger_tx WHERE kind='liquidation'").fetchall())
        self.assertEqual(left, 0)
        self.assertIn("продажа запасов", memos)
        w = game_server.wallet("alice")[1]
        self.assertGreater(w["balance"], 0)
        self.assert_ledger_balanced()

    def test_site_can_be_built_on_again_after_liquidation(self):
        self.build("alice", "factory")
        self.set_cash("alice", 60_000)
        site_y = 10 + 7 * self.cursor
        self.month("alice", 5)
        self.set_cash("alice", 5_000_000)
        status, res = game_server.build("alice", {"kind": "factory", "x": 8, "y": site_y, "request_id": str(uuid.uuid4())})
        self.assertEqual(status, 201, res)

    def test_other_companies_are_unaffected(self):
        self.build("bob", "farm")
        self.idle_factory("alice")
        self.month("alice", 5)
        self.assertEqual(game_server.wallet("bob")[1]["company"]["bankruptcies"], 0)
        self.assertEqual(game_server.wallet("bob")[1]["holdings"], {"farm": 1})

    def test_company_can_restart_after_bankruptcy(self):
        self.go_bankrupt()
        self.set_cash("alice", 2_000_000)
        self.build("alice", "farm")
        w = self.month("alice", 2)
        self.assertEqual(w["holdings"], {"farm": 1})
        self.assertEqual(w["company"]["bankruptcies"], 1)       # history is kept

    def test_ledger_balanced_through_bankruptcy(self):
        self.go_bankrupt()
        self.assert_ledger_balanced()


class NpcInvestorTests(BankruptcyBase):
    def test_needs_investor_rules(self):
        base = {"balance": 1000, "holdings": {}, "company": {"last_bankruptcy_month": 10}}
        self.assertTrue(npc.needs_investor(base, 10 + economy.NPC_RECAPITAL_MONTHS))
        self.assertFalse(npc.needs_investor(base, 10 + economy.NPC_RECAPITAL_MONTHS - 1))
        self.assertFalse(npc.needs_investor(dict(base, holdings={"farm": 1}), 99))
        self.assertFalse(npc.needs_investor(dict(base, balance=economy.START_CAPITAL), 99))
        self.assertFalse(npc.needs_investor({"balance": 0, "holdings": {}, "company": {"last_bankruptcy_month": None}}, 99))

    def test_bankrupt_npc_gets_a_new_investor_later(self):
        game_server.npc_tick()
        owner = npc.PERSONAS[0]["owner"]
        self.set_cash(owner, 1000)
        with game_server.connect() as db:      # as after a liquidation: no buildings, a bankruptcy on record
            db.execute("DELETE FROM cells WHERE object_id IN (SELECT id FROM buildings WHERE owner=?)", (owner,))
            db.execute("DELETE FROM building_ops WHERE owner=?", (owner,))
            db.execute("DELETE FROM buildings WHERE owner=?", (owner,))
            db.execute("INSERT INTO company_status(owner,missed,wages_owed,input_owed,maint_owed,bankruptcies,last_bankruptcy_month,written_off) VALUES(?,0,0,0,0,1,0,0) "
                       "ON CONFLICT(owner) DO UPDATE SET bankruptcies=1,last_bankruptcy_month=0", (owner,))
        for _ in range(economy.NPC_RECAPITAL_MONTHS + 2):
            self.now += DAY + 5
            game_server.npc_tick()
        with game_server.connect() as db:
            invested = db.execute("SELECT COUNT(*) FROM ledger_tx WHERE kind='recapital'").fetchone()[0]
        self.assertGreaterEqual(invested, 1)
        self.assertGreater(game_server.wallet(owner)[1]["balance"], 1000)


if __name__ == "__main__":
    unittest.main()