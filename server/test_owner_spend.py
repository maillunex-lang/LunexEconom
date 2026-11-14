"""Owners return a share of after-tax profit to the market."""
import os
import tempfile
import unittest
import uuid
from unittest import mock

import economy
import game_server

DAY = 86400
T0 = 1_800_000_000


class OwnerSpendTests(unittest.TestCase):
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

    def month(self, n=1):
        self.now += DAY * n + 5
        return game_server.wallet("alice")[1]

    def test_a_profitable_farm_spends_and_the_market_is_paid(self):
        self.build("alice", "farm")
        self.month(1)
        with game_server.connect() as db:
            row = db.execute("SELECT amount FROM eco_owner_spend WHERE owner='alice'").fetchone()
            market = db.execute("SELECT COALESCE(SUM(e.amount),0) FROM ledger_entries e JOIN ledger_tx t ON t.id=e.tx_id "
                                "WHERE t.kind='owner_spend' AND e.account=?", (economy.MARKET_ACCOUNT,)).fetchone()[0]
            player = db.execute("SELECT COALESCE(SUM(e.amount),0) FROM ledger_entries e JOIN ledger_tx t ON t.id=e.tx_id "
                                "WHERE t.kind='owner_spend' AND e.account=?", (economy.player_account("alice"),)).fetchone()[0]
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
        self.assertIsNotNone(row)
        self.assertGreater(row[0], 0)
        self.assertEqual(market, row[0])
        self.assertEqual(player, -row[0])
        self.assertEqual((bad, total), ([], 0))
        report = game_server.wallet("alice")[1]["reports"][0]
        self.assertEqual(report["owner_spent"], row[0])
        self.assertGreater(game_server.wallet("alice")[1]["forecast"]["owner_spend"], 0)

    def test_a_broke_factory_does_not_spend_its_reserve(self):
        self.build("alice", "factory")          # no oil and honey of its own: it cannot run
        with game_server.connect() as db:
            db.execute("UPDATE wallets SET balance=0 WHERE account=?", (economy.player_account("alice"),))
        self.month(1)
        with game_server.connect() as db:
            spent = db.execute("SELECT COUNT(*) FROM eco_owner_spend").fetchone()[0]
        self.assertEqual(spent, 0)

    def test_the_same_month_is_not_spent_twice(self):
        self.build("alice", "farm")
        self.month(1)
        game_server.wallet("alice")
        with game_server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM eco_owner_spend").fetchone()[0], 1)

    def test_share_is_the_configured_fraction_of_after_tax_profit(self):
        self.build("alice", "farm")
        wallet = self.month(1)
        report = wallet["reports"][0]
        with game_server.connect() as db:
            tax = db.execute("SELECT profit_tax,property_tax FROM company_taxes WHERE owner='alice'").fetchone()
        after_tax = report["profit"] - int(tax[0]) - int(tax[1])
        # profit in the report is revenue - inputs - paid wages - paid maintenance, which is the base before tax
        # minus interest (none). Property tax is not inside `profit`, profit tax is not either.
        self.assertAlmostEqual(report["owner_spent"], int(after_tax * economy.OWNER_SPEND_SHARE), delta=1)
        self.assertGreater(wallet["balance"], economy.START_CAPITAL // 2)
