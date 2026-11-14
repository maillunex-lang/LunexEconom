import os
import tempfile
import unittest
import uuid
from unittest import mock

import bank
import economy
import game_server

DAY = 86400
T0 = 1_800_000_000


class BankBase(unittest.TestCase):
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

    def mature(self, who):
        """Age the company and record enough revenue that the full collateral limit applies."""
        game_server.wallet(who)
        with game_server.connect() as db:
            db.execute("UPDATE building_ops SET start_month=start_month-? WHERE owner=?", (economy.LOAN_RAMP_MONTHS + 2, who))
            for index in range(economy.LOAN_REVENUE_MONTHS):
                db.execute("INSERT INTO company_reports(owner,month_index,revenue,input_cost,upkeep,profit,buildings) VALUES(?,?,?,?,?,?,?) "
                           "ON CONFLICT(owner,month_index) DO UPDATE SET revenue=excluded.revenue",
                           (who, -(index + 1), economy.LOAN_REVENUE_PROOF, 0, 0, 0, 1))

    def loan(self, who, action, amount=None, request_id=None):
        payload = {"action": action, "request_id": request_id or str(uuid.uuid4())}
        if amount is not None:
            payload["amount"] = amount
        return game_server.loan(who, payload)

    def month(self, who="alice", n=1):
        self.now += DAY * n + 5
        return game_server.wallet(who)[1]

    def set_cash(self, who, amount):
        game_server.wallet(who)
        account = economy.player_account(who)
        with game_server.connect() as db:
            current = db.execute("SELECT balance FROM wallets WHERE account=?", (account,)).fetchone()[0]
            db.execute("UPDATE wallets SET balance=? WHERE account=?", (amount, account))
            db.execute("UPDATE wallets SET balance=balance-? WHERE account=?", (amount - current, economy.TREASURY))

    def ledger_ok(self):
        with game_server.connect() as db:
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
            neg = db.execute("SELECT 1 FROM wallets WHERE account LIKE 'player:%' AND balance<0").fetchall()
        self.assertEqual((bad, total, neg), ([], 0, []))


class LimitTests(BankBase):
    def test_no_collateral_no_credit(self):
        w = game_server.wallet("alice")[1]
        self.assertEqual(w["loan"]["limit"], 0)
        status, res = self.loan("alice", "take", 100_000)
        self.assertEqual((status, res["error"]), (409, "limit_exceeded"))

    def test_newcomer_limit_is_a_small_share_and_a_mature_company_gets_half(self):
        self.build("alice", "factory")
        self.build("alice", "farm")
        fresh = game_server.wallet("alice")[1]["loan"]
        worth = 450_000 + 120_000
        self.assertEqual(fresh["limit"], int(worth * economy.LOAN_NEW_LTV))
        self.assertLess(fresh["limit"], int(worth * economy.LOAN_LTV))
        self.assertIn("Новичок", fresh["limit_reason"])
        self.mature("alice")
        grown = game_server.wallet("alice")[1]["loan"]
        self.assertEqual(grown["limit"], int(worth * economy.LOAN_LTV))
        self.assertGreaterEqual(grown["age_months"], economy.LOAN_RAMP_MONTHS)
        self.assertIn("Полный лимит", grown["limit_reason"])

    def test_age_alone_or_revenue_alone_does_not_open_the_full_limit(self):
        self.build("alice", "factory")
        worth = 450_000
        floor = int(worth * economy.LOAN_NEW_LTV)
        full = int(worth * economy.LOAN_LTV)
        game_server.wallet("alice")
        with game_server.connect() as db:
            opened = db.execute("SELECT start_month FROM building_ops WHERE owner='alice'").fetchone()[0]
            db.execute("UPDATE building_ops SET start_month=? WHERE owner='alice'", (opened - economy.LOAN_RAMP_MONTHS - 2,))
        aged = game_server.wallet("alice")[1]["loan"]
        self.assertGreaterEqual(aged["age_months"], economy.LOAN_RAMP_MONTHS)
        self.assertEqual(aged["revenue_avg"], 0)
        self.assertEqual(aged["limit"], floor)          # old, but no confirmed revenue
        self.assertLess(aged["limit"], full)
        with game_server.connect() as db:
            db.execute("UPDATE building_ops SET start_month=? WHERE owner='alice'", (opened,))
            db.execute("INSERT INTO company_reports(owner,month_index,revenue,input_cost,upkeep,profit,buildings) VALUES(?,?,?,?,?,?,?) "
                       "ON CONFLICT(owner,month_index) DO UPDATE SET revenue=excluded.revenue",
                       ("alice", opened - 1, economy.LOAN_REVENUE_PROOF * 3, 0, 0, 0, 1))
        rich = game_server.wallet("alice")[1]["loan"]
        self.assertEqual(rich["age_months"], 0)
        self.assertGreaterEqual(rich["revenue_avg"], economy.LOAN_REVENUE_PROOF)
        self.assertEqual(rich["limit"], floor)          # revenue without time does not open the rest
        self.assertIn("Новичок", rich["limit_reason"])

    def test_limit_is_capped(self):
        with mock.patch.object(economy, "LOAN_MAX", 50_000):
            self.build("alice", "factory")
            self.assertEqual(game_server.wallet("alice")[1]["loan"]["limit"], 50_000)

    def test_invalid_requests(self):
        self.build("alice", "factory")
        self.assertEqual(self.loan("alice", "take", 5)[1]["error"], "invalid_amount")
        self.assertEqual(self.loan("alice", "take", "100000")[1]["error"], "invalid_amount")
        self.assertEqual(self.loan("alice", "burn", 100_000)[1]["error"], "invalid_action")
        self.assertEqual(game_server.loan("alice", {"action": "take", "amount": 100_000, "request_id": "bad"})[0], 400)


class TakeAndRepayTests(BankBase):
    def test_take_credits_the_wallet_and_ledger_stays_balanced(self):
        self.build("alice", "factory")
        self.mature("alice")
        before = game_server.wallet("alice")[1]["balance"]
        status, res = self.loan("alice", "take", 200_000)
        self.assertEqual(status, 201, res)
        self.assertEqual(res["balance"], before + 200_000)
        self.assertEqual(res["loan"]["balance"], 200_000)
        self.assertEqual(res["loan"]["available"], int(450_000 * economy.LOAN_LTV) - 200_000)
        self.ledger_ok()

    def test_cannot_exceed_the_limit(self):
        self.build("alice", "farm")
        newcomer = int(120_000 * economy.LOAN_NEW_LTV)
        status, res = self.loan("alice", "take", newcomer + 1_000)
        self.assertEqual((status, res["error"]), (409, "limit_exceeded"))
        self.assertEqual(res["limit"], newcomer)
        self.assertEqual(self.loan("alice", "take", newcomer)[0], 201)
        self.build("bob", "farm")
        self.mature("bob")
        self.assertEqual(self.loan("bob", "take", 70_000)[1]["error"], "limit_exceeded")
        self.assertEqual(self.loan("bob", "take", 60_000)[0], 201)
        self.assertEqual(self.loan("bob", "take", 10_000)[1]["error"], "limit_exceeded")

    def test_take_is_idempotent(self):
        self.build("alice", "factory")
        self.mature("alice")
        rid = str(uuid.uuid4())
        a = self.loan("alice", "take", 100_000, rid)
        balance = game_server.wallet("alice")[1]["balance"]
        b = self.loan("alice", "take", 100_000, rid)
        self.assertEqual((a[0], b[0]), (201, 200))
        self.assertEqual(game_server.wallet("alice")[1]["balance"], balance)
        self.assertEqual(game_server.wallet("alice")[1]["loan"]["balance"], 100_000)

    def test_partial_and_full_repayment(self):
        self.build("alice", "factory")
        self.mature("alice")
        self.loan("alice", "take", 150_000)
        status, res = self.loan("alice", "repay", 50_000)
        self.assertEqual((status, res["loan"]["balance"]), (201, 100_000))
        status, res = self.loan("alice", "repay")              # everything
        self.assertEqual((status, res["loan"]["balance"]), (201, 0))
        self.assertEqual(self.loan("alice", "repay", 1000)[1]["error"], "no_loan")
        self.ledger_ok()

    def test_cannot_repay_more_than_cash(self):
        self.build("alice", "factory")
        self.mature("alice")
        self.loan("alice", "take", 200_000)
        self.set_cash("alice", 10_000)
        self.assertEqual(self.loan("alice", "repay", 50_000)[1]["error"], "insufficient_funds")
        self.assertEqual(self.loan("alice", "repay")[1]["loan"]["balance"], 190_000)    # "all" repays what the cash allows

    def test_overpayment_is_trimmed_to_the_debt(self):
        self.build("alice", "factory")
        self.mature("alice")
        self.loan("alice", "take", 100_000)
        status, res = self.loan("alice", "repay", 500_000)
        self.assertEqual((status, res["repaid"], res["loan"]["balance"]), (201, 100_000, 0))


class InterestTests(BankBase):
    def test_interest_is_paid_monthly_from_cash(self):
        self.build("alice", "farm")
        self.mature("alice")
        self.loan("alice", "take", 60_000)
        w = self.month("alice", 3)
        self.assertEqual(w["loan"]["balance"], 60_000)          # interest paid in cash, principal untouched
        self.assertEqual(w["loan"]["monthly_interest"], 900)
        with game_server.connect() as db:
            paid = db.execute("SELECT interest_paid FROM loans WHERE owner='alice'").fetchone()[0]
            bank_balance = db.execute("SELECT balance FROM wallets WHERE account=?", (economy.BANK,)).fetchone()[0]
        self.assertEqual(paid, 3 * 900)
        self.assertEqual(bank_balance, -60_000 + 3 * 900)
        self.ledger_ok()

    def test_forecast_includes_interest(self):
        self.build("alice", "farm")
        self.mature("alice")
        base = game_server.wallet("alice")[1]["forecast"]
        self.loan("alice", "take", 60_000)
        f = game_server.wallet("alice")[1]["forecast"]
        self.assertEqual(f["interest"], 900)
        self.assertEqual(f["profit"], base["profit"] - 900)

    def test_unpaid_interest_is_capitalized_and_counts_as_missed(self):
        self.build("alice", "factory")
        self.mature("alice")
        self.loan("alice", "take", 200_000)
        self.set_cash("alice", 0)
        w = self.month("alice", 1)
        self.assertGreater(w["loan"]["balance"], 200_000)       # interest added to the loan
        self.assertGreaterEqual(w["company"]["missed"], 1)

    def test_no_new_credit_while_in_default(self):
        self.build("alice", "factory")
        self.mature("alice")
        self.loan("alice", "take", 100_000)
        self.set_cash("alice", 0)
        self.month("alice", 1)
        w = game_server.wallet("alice")[1]
        self.assertTrue(w["loan"]["in_default"])
        self.assertEqual(w["loan"]["available"], 0)
        self.assertEqual(self.loan("alice", "take", 10_000)[1]["error"], "in_default")


class BankruptcyWithLoanTests(BankBase):
    def test_bank_is_the_last_creditor_and_loses_the_rest(self):
        self.build("alice", "factory")                          # no suppliers: pure cost
        self.mature("alice")
        self.loan("alice", "take", 220_000)
        self.set_cash("alice", 60_000)
        w = self.month("alice", 8)
        self.assertEqual(w["company"]["bankruptcies"], 1)
        self.assertEqual(w["loan"]["balance"], 0)                # written off or repaid
        self.assertGreaterEqual(w["balance"], 0)
        self.ledger_ok()

    def test_written_off_loan_is_covered_by_the_treasury_and_the_bank_returns_to_zero(self):
        import economy
        self.build("alice", "factory")
        self.mature("alice")
        self.loan("alice", "take", 220_000)
        self.set_cash("alice", 60_000)
        with game_server.connect() as db:
            bank_before = db.execute("SELECT balance FROM wallets WHERE account=?", (economy.BANK,)).fetchone()[0]
            treasury_before = db.execute("SELECT balance FROM wallets WHERE account=?", (economy.TREASURY,)).fetchone()[0]
        w = self.month("alice", 8)
        self.assertEqual(w["company"]["bankruptcies"], 1)
        with game_server.connect() as db:
            bank = db.execute("SELECT balance FROM wallets WHERE account=?", (economy.BANK,)).fetchone()[0]
            loans_left = db.execute("SELECT COALESCE(SUM(balance),0) FROM loans").fetchone()[0]
            memos = [m for (m,) in db.execute("SELECT memo FROM ledger_tx WHERE kind='loan' AND memo LIKE 'Списание%'").fetchall()]
            treasury = db.execute("SELECT balance FROM wallets WHERE account=?", (economy.TREASURY,)).fetchone()[0]
        self.assertEqual(loans_left, 0)
        self.assertTrue(memos)                                   # the write-off was posted to the ledger
        self.assertGreaterEqual(bank, bank_before)               # the bank no longer carries a loan that does not exist
        self.assertLess(treasury, treasury_before)               # the Republic took the loss
        self.ledger_ok()

    def test_proceeds_repay_the_bank_when_there_is_enough(self):
        self.build("alice", "factory")
        self.mature("alice")
        self.loan("alice", "take", 50_000)
        self.set_cash("alice", 60_000)
        self.month("alice", 8)
        with game_server.connect() as db:
            repaid = db.execute("SELECT repaid_total FROM loans WHERE owner='alice'").fetchone()[0]
        self.assertGreater(repaid, 0)
        self.ledger_ok()


class SellWithLoanTests(BankBase):
    def test_selling_the_last_building_repays_the_loan_first(self):
        res = self.build("alice", "farm")
        self.mature("alice")
        self.loan("alice", "take", 60_000)
        status, out = game_server.sell("alice", {"object_id": res["object_id"], "request_id": str(uuid.uuid4())})
        self.assertEqual(status, 201)
        w = game_server.wallet("alice")[1]
        self.assertLess(w["loan"]["balance"], 60_000)
        self.ledger_ok()

    def test_loan_without_buildings_still_costs_interest(self):
        res = self.build("alice", "farm")
        self.mature("alice")
        self.loan("alice", "take", 60_000)
        self.set_cash("alice", 1_000_000)
        with game_server.connect() as db:
            db.execute("DELETE FROM cells WHERE object_id=?", (res["object_id"],))
            db.execute("DELETE FROM building_ops WHERE owner='alice'")
            db.execute("DELETE FROM buildings WHERE owner='alice'")
        before = game_server.wallet("alice")[1]["balance"]
        w = self.month("alice", 1)
        self.assertEqual(w["balance"], before - 900)
        self.ledger_ok()


if __name__ == "__main__":
    unittest.main()
