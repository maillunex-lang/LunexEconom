"""EX-09 NPC banks, shares and tax schedule. The legacy loans table stays untouched."""
import os
import tempfile
import unittest
import uuid
from unittest import mock

import balance
import balance_targets
import bank
import banking
import economy
import game_server


DAY = 86400
T0 = 1_800_000_000


class BankingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = game_server.DB
        game_server.DB = os.path.join(self.tmp.name, "w.sqlite3")
        self.now = T0
        patch = mock.patch.object(game_server.time, "time", side_effect=lambda: self.now)
        patch.start()
        self.cursor = 0
        self.addCleanup(patch.stop)
        self.addCleanup(self._restore)

    def _restore(self):
        game_server.DB = self.old
        self.tmp.cleanup()
        for name in ("BANKS_ENABLED", "TAX_EXTRAS_ENABLED", "CREDIT_BOOM"):
            os.environ.pop("LUNEX_BAL_" + name, None)
        balance.reload()

    def _on(self):
        os.environ["LUNEX_BAL_BANKS_ENABLED"] = "1"
        balance.reload()

    def build(self, who="alice", kind="farm"):
        for _ in range(400):
            self.cursor += 1
            status, res = game_server.build(who, {"kind": kind, "x": 8, "y": 10 + 7 * self.cursor, "request_id": str(uuid.uuid4())})
            if status == 201:
                return res
        self.fail("no site")

    def test_disabled_refuses_and_old_loan_table_still_works(self):
        self.build()
        status, body = game_server.bank_loan("alice", {
            "bank": "bashkredit", "product": "working_capital", "collateral": "realty",
            "amount": 10_000, "request_id": str(uuid.uuid4())})
        self.assertEqual((status, body["error"]), (409, "banks_disabled"))
        self.mature_and_take_legacy()
        with game_server.connect() as db:
            legacy = db.execute("SELECT COUNT(*) FROM loans").fetchone()[0]
            npc = db.execute("SELECT COUNT(*) FROM bank_npc_loans").fetchone()[0]
        self.assertEqual(legacy, 1)
        self.assertEqual(npc, 0)

    def mature_and_take_legacy(self):
        game_server.wallet("alice")
        with game_server.connect() as db:
            db.execute("UPDATE building_ops SET start_month=start_month-? WHERE owner=?", (economy.LOAN_RAMP_MONTHS + 2, "alice"))
            for index in range(economy.LOAN_REVENUE_MONTHS):
                db.execute(
                    "INSERT INTO company_reports(owner,month_index,revenue,input_cost,upkeep,profit,buildings) VALUES(?,?,?,?,?,?,?) "
                    "ON CONFLICT(owner,month_index) DO UPDATE SET revenue=excluded.revenue",
                    ("alice", -(index + 1), economy.LOAN_REVENUE_PROOF, 0, 0, 0, 1))
            db.commit()
        status, body = game_server.loan("alice", {"action": "take", "amount": 10_000, "request_id": str(uuid.uuid4())})
        self.assertEqual(status, 201, body)

    def test_loan_replay_repay_shares_and_rates(self):
        self._on()
        self.build()
        request_id = str(uuid.uuid4())
        payload = {"bank": "bashkredit", "product": "working_capital", "collateral": "realty",
                   "amount": 10_000, "request_id": request_id}
        status, body = game_server.bank_loan("alice", payload)
        self.assertEqual(status, 201, body)
        self.assertGreaterEqual(body["rate_year"], 0.05)
        self.assertLessEqual(body["rate_year"], 0.40)
        again = game_server.bank_loan("alice", payload)
        self.assertEqual(again[0], 200)
        self.assertEqual(again[1]["loan_id"], body["loan_id"])
        with game_server.connect() as db:
            draws = db.execute("SELECT COUNT(*) FROM ledger_tx WHERE kind='npc_loan' AND memo LIKE 'Кредит%'").fetchone()[0]
        self.assertEqual(draws, 1)
        status, repaid = game_server.bank_repay("alice", {"loan_id": body["loan_id"], "amount": 10_000, "request_id": str(uuid.uuid4())})
        self.assertEqual(status, 201, repaid)
        self.assertEqual(repaid["balance"], 0)
        share_id = str(uuid.uuid4())
        status, bought = game_server.shares_buy("alice", {"company": "acme", "shares": 10, "price": 1000, "request_id": share_id})
        self.assertEqual(status, 201, bought)
        self.assertEqual(game_server.shares_buy("alice", {"company": "acme", "shares": 10, "price": 1000, "request_id": share_id})[0], 200)
        with game_server.connect() as db:
            economy.post(db, "?", "seed", "резерв дивиденда",
                         [(economy.TREASURY, -200_000), (economy.player_account("acme"), 200_000)], self.now)
            banking.monthly(db, "?", 3, self.now)
            paid = db.execute("SELECT amount FROM dividend_paid WHERE company='acme'").fetchone()[0]
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
            db.commit()
        self.assertGreater(paid, 0)
        self.assertEqual((bad, total), ([], 0))
        self.assertEqual(balance_targets.check({"loan_rate_year": body["rate_year"]}), [])

    def test_unknown_product_and_foreclosure_do_not_mint_money(self):
        self._on()
        self.build()
        status, body = game_server.bank_loan("alice", {
            "bank": "uralinvest", "product": "mortgage", "collateral": "realty",
            "amount": 10_000, "request_id": str(uuid.uuid4())})
        self.assertEqual(body["error"], "product_not_offered")
        status, body = game_server.bank_loan("alice", {
            "bank": "bashkredit", "product": "working_capital", "collateral": "inventory",
            "amount": 10_000, "request_id": str(uuid.uuid4())})
        self.assertEqual(body["error"], "insufficient_collateral")
        with game_server.connect() as db:
            value = banking.collateral_value(db, "?", "alice", "realty")
            rate = banking.quote_rate(db, "?", "alice", "agroprombank", "working_capital", "realty")
            banking._open(db, "?", "alice", banking._bank("bashkredit"), "working_capital", 10_000, "realty", value, 0, self.now, "manual")
            account = economy.player_account("alice")
            cash = economy.balance(db, "?", "alice") or 0
            if cash:
                economy.post(db, "?", "test", "обнуление кассы", [(account, -cash), (economy.TREASURY, cash)], self.now)
            db.execute("UPDATE bank_npc_loans SET missed=3 WHERE request_id='manual'")
            banking.monthly(db, "?", 1, self.now)
            row = db.execute("SELECT status,missed FROM bank_npc_loans WHERE request_id='manual'").fetchone()
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
            db.commit()
        self.assertGreaterEqual(rate, 0.05)
        self.assertLessEqual(rate, 0.40)
        self.assertEqual(row[0], "defaulted")
        self.assertEqual((bad, int(total)), ([], 0))

    def test_tax_schedule_is_registry_and_extras_are_opt_in(self):
        rates = banking.tax_rates()
        self.assertEqual(rates["profit"], balance.get("DEFAULT_PROFIT_TAX"))
        self.assertEqual(rates["land"], balance.get("LAND_TAX"))
        self.assertFalse(rates["extras_enabled"])
        os.environ["LUNEX_BAL_TAX_EXTRAS_ENABLED"] = "1"
        balance.reload()
        with game_server.connect() as db:
            economy.ensure_wallet(db, "?", "alice", self.now)
            db.execute(
                "INSERT INTO company_reports(owner,month_index,revenue,input_cost,upkeep,profit,buildings) VALUES(?,?,?,?,?,?,?)",
                ("alice", 0, 100_000, 0, 0, 10_000, 1))
            banking.monthly(db, "?", 0, self.now)
            banking.monthly(db, "?", 0, self.now)
            rows = db.execute("SELECT paid FROM tax_extra_posted").fetchall()
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
            db.commit()
        self.assertEqual(len(rows), 1)
        self.assertGreater(rows[0][0], 0)
        self.assertEqual((bad, total), ([], 0))
        self.assertEqual(bank.balance.__name__, "balance")


if __name__ == "__main__":
    unittest.main()
