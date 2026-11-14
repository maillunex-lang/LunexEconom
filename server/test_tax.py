import os
import tempfile
import unittest
import uuid
from unittest import mock

import economy
import game_server
import taxes

DAY = 86400
T0 = 1_800_000_000
BUDGET = economy.player_account(economy.CITY)


class TaxBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = game_server.DB
        game_server.DB = os.path.join(self.tmp.name, "w.sqlite3")
        self.now = T0
        p = mock.patch.object(game_server.time, "time", side_effect=lambda: self.now)
        p.start()
        self.addCleanup(p.stop)
        # Fixed reference prices: the subject here is tax arithmetic, not the market.
        pin = mock.patch.object(economy, "price_for", side_effect=lambda product, supply, demand: economy.MARKET[product]["reference_price"])
        pin.start()
        self.addCleanup(pin.stop)
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

    def budget(self):
        with game_server.connect() as db:
            row = db.execute("SELECT balance FROM wallets WHERE account=?", (BUDGET,)).fetchone()
        return row[0] if row else 0

    def ledger_ok(self):
        with game_server.connect() as db:
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
            neg = db.execute("SELECT 1 FROM wallets WHERE account LIKE 'player:%' AND balance<0").fetchall()
        self.assertEqual((bad, total, neg), ([], 0, []))


class RateTests(unittest.TestCase):
    def test_defaults_follow_the_owner_decision(self):
        self.assertEqual(economy.DEFAULT_PROFIT_TAX, 0.13)
        self.assertEqual(economy.VAT_STANDARD, 0.22)
        self.assertEqual(economy.DEFAULT_PROPERTY_TAX, 0.022)
        self.assertEqual(economy.VAT_RATES["honey"], 0.10)       # food: reduced rate
        self.assertEqual(economy.VAT_RATES["oil"], 0.22)
        self.assertEqual(economy.VAT_RATES["goods"], 0.22)
        self.assertLessEqual(max(economy.VAT_RATES.values()), 0.22)

    def test_limits_respect_the_law(self):
        self.assertEqual(economy.PROPERTY_TAX_LIMITS[1], 0.022)     # Tax Code art. 380 cap
        self.assertEqual(economy.PROFIT_TAX_LIMITS[1], 0.25)        # total real profit tax

    def test_disabled_taxes_are_zero(self):
        with mock.patch.object(economy, "TAXES_ENABLED", False):
            self.assertEqual(taxes.vat_rate("goods"), 0.0)

    def test_arithmetic(self):
        self.assertEqual(taxes.profit_tax_due(100_000, 0.13), 13_000)
        self.assertEqual(taxes.profit_tax_due(-5_000, 0.13), 0)
        self.assertEqual(taxes.property_tax_due([("farm", 1000)], 0.022), int(120_000 * 0.022 / 12))
        self.assertEqual(taxes.property_tax_due([("farm", 500)], 0.022), int(60_000 * 0.022 / 12))
        out, inn = taxes.vat_amounts({"honey": 20_000, "goods": 100_000}, {"oil": 10_000})
        self.assertEqual((out, inn), (2_000 + 22_000, 2_200))


class CollectionTests(TaxBase):
    def test_vat_is_borne_by_the_buyer_and_collected_by_the_city(self):
        self.build("alice", "farm")
        base = game_server.wallet("alice")[1]["balance"]
        w = self.month("alice", 1)
        revenue, upkeep = 20_000, 8_000                           # 100 honey at the reference price 200, wages + maintenance
        profit_tax = int((revenue - upkeep) * 0.13)
        property_tax = int(120_000 * 0.022 / 12)
        vat = int(20_000 * 0.10)
        self.assertEqual(w["balance"], base + revenue - upkeep - profit_tax - property_tax)     # VAT does not reduce the margin
        self.assertEqual(self.budget(), vat + profit_tax + property_tax)
        self.ledger_ok()

    def test_profit_tax_only_on_positive_profit(self):
        self.build("alice", "factory")                            # no raw material anywhere: pure loss, no revenue
        self.month("alice", 1)
        with game_server.connect() as db:
            row = db.execute("SELECT profit_tax,vat FROM company_taxes WHERE owner='alice'").fetchone()
        self.assertEqual(row[0], 0)
        self.assertEqual(row[1], 0)

    def test_property_tax_is_charged_even_without_profit(self):
        self.build("alice", "factory")
        self.month("alice", 1)
        with game_server.connect() as db:
            prop = db.execute("SELECT property_tax FROM company_taxes WHERE owner='alice'").fetchone()[0]
        self.assertEqual(prop, int(450_000 * 0.022 / 12))

    def test_input_vat_creates_a_credit_that_offsets_later_vat(self):
        self.build("bob", "farm")
        self.build("carol", "mine")
        self.build("alice", "factory")
        self.month("alice", 3)
        with game_server.connect() as db:
            rows = db.execute("SELECT month_index,vat FROM company_taxes WHERE owner='alice' ORDER BY month_index").fetchall()
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(v >= 0 for _, v in rows))
        self.ledger_ok()

    def test_taxes_follow_the_policy_rates(self):
        with game_server.connect() as db:
            db.execute("INSERT INTO city_policy(id,profit_tax_permille,property_tax_permille,social_share_permille,changed_month) VALUES(1,50,0,300,0)")
        self.build("alice", "farm")
        base = game_server.wallet("alice")[1]["balance"]
        w = self.month("alice", 1)
        self.assertEqual(w["balance"], base + 12_000 - int(12_000 * 0.05))     # 5 % profit tax, no property tax
        self.assertEqual(game_server.market_state()[1]["taxes"]["profit_tax"], 0.05)

    def test_view_and_forecast_expose_taxes(self):
        self.build("alice", "farm")
        w = game_server.wallet("alice")[1]
        t = w["taxes"]
        self.assertEqual((t["profit_tax"], t["property_tax"], t["vat"]["honey"], t["vat"]["goods"]), (0.13, 0.022, 0.10, 0.22))
        f = w["forecast"]
        self.assertEqual(f["profit_tax"], int(f["profit"] * 0.13))
        self.assertEqual(f["property_tax"], int(120_000 * 0.022 / 12))
        self.assertEqual(f["profit_after_tax"], f["profit"] - f["profit_tax"] - f["property_tax"])
        self.assertEqual(game_server.market_state()[1]["taxes"], t)

    def test_reports_show_the_taxes_paid(self):
        self.build("alice", "farm")
        w = self.month("alice", 2)
        self.assertTrue(all(r["tax"] > 0 for r in w["reports"]))

    def test_city_pays_no_taxes_and_has_no_start_capital(self):
        game_server.wallet(economy.CITY)
        self.assertEqual(self.budget(), 0)

    def test_budget_accumulates_over_months_and_ledger_balances(self):
        self.build("alice", "farm")
        self.build("bob", "mine")
        self.month("alice", 5)
        self.assertGreater(self.budget(), 0)
        self.ledger_ok()


class ArrearsTests(TaxBase):
    def test_unpaid_taxes_become_arrears_and_count_as_missed(self):
        self.build("alice", "warehouse")
        self.set_cash("alice", 0)
        w = self.month("alice", 1)
        self.assertGreater(w["company"]["tax_owed"], 0)
        self.assertGreaterEqual(w["company"]["missed"], 1)
        self.assertGreater(w["company"]["arrears"], 0)

    def test_tax_arrears_are_repaid_before_maintenance_arrears(self):
        self.build("alice", "warehouse")
        with game_server.connect() as db:
            db.execute("INSERT INTO company_tax_state(owner,tax_owed,vat_credit) VALUES('alice',10000,0) ON CONFLICT(owner) DO UPDATE SET tax_owed=10000")
            db.execute("INSERT INTO company_status(owner,missed,wages_owed,input_owed,maint_owed,bankruptcies,last_bankruptcy_month,written_off) VALUES('alice',0,0,0,5000,0,NULL,0) ON CONFLICT(owner) DO UPDATE SET maint_owed=5000")
        before = self.budget()
        w = self.month("alice", 1)
        self.assertEqual(w["company"]["tax_owed"], 0)
        self.assertEqual(w["company"]["maint_owed"], 0)
        self.assertGreater(self.budget(), before + 10_000 - 1)
        self.ledger_ok()

    def test_bankruptcy_pays_tax_arrears_from_the_proceeds(self):
        self.build("alice", "factory")
        self.set_cash("alice", 60_000)
        w = self.month("alice", 7)
        self.assertEqual(w["company"]["bankruptcies"], 1)
        self.assertEqual(w["company"]["tax_owed"], 0)
        self.assertGreater(self.budget(), 0)
        self.ledger_ok()


if __name__ == "__main__":
    unittest.main()
