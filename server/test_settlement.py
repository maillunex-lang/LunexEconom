import os
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


class SettlementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = game_server.DB
        game_server.DB = os.path.join(self.tmp.name, "w.sqlite3")
        self.now = T0
        patcher = mock.patch.object(game_server.time, "time", side_effect=lambda: self.now)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Pin market prices to the reference price: this file tests settlement, test_market.py tests pricing.
        pin = mock.patch.object(economy, "price_for", side_effect=lambda product, supply, demand: economy.MARKET[product]["reference_price"])
        pin.start()
        self.addCleanup(pin.stop)

    def tearDown(self):
        game_server.DB = self.old
        self.tmp.cleanup()

    def build(self, kind="farm", x=8, y=10, who="alice"):
        return game_server.build(who, {"kind": kind, "x": x, "y": y, "request_id": rid()})

    def balance(self, who="alice"):
        return game_server.wallet(who)[1]["balance"]

    def test_economy_terms_include_production(self):
        t = economy.terms()["production"]["farm"]
        self.assertEqual((t["output"], t["unit_price"], t["upkeep"], t["jobs"]), (100, 200, 2000, 4))

    def test_no_income_before_month_ends(self):
        status, res = self.build()
        self.assertEqual(status, 201)
        self.now += DAY - 10
        self.assertEqual(self.balance(), res["balance"])

    def test_first_month_paid_after_it_ends(self):
        _, res = self.build()
        self.now += DAY + 5
        w = game_server.wallet("alice")[1]
        self.assertEqual(w["balance"], res["balance"] + 12_000)   # 100*200 - 8000
        self.assertEqual(len(w["reports"]), 1)
        self.assertEqual(w["reports"][0]["profit"], 12_000)
        self.assertEqual(w["forecast"], {"revenue": 20_000, "input_cost": 0, "upkeep": 8_000, "wages": 6_000, "profit": 12_000, "buildings": 1})

    def test_settlement_is_idempotent(self):
        _, res = self.build()
        self.now += DAY * 2 + 5
        first = self.balance()
        self.assertEqual(self.balance(), first)
        self.assertEqual(first, res["balance"] + 24_000)

    def test_catch_up_over_many_months(self):
        _, res = self.build()
        self.now += DAY * 6 + 5
        self.assertEqual(self.balance(), res["balance"] + 6 * 12_000)

    def test_first_month_is_prorated(self):
        game_server.wallet("alice")      # starts the clock at T0
        self.now += DAY // 2             # building is created half-way through month 0
        _, res = self.build()
        self.now += DAY // 2 + 5
        self.assertEqual(self.balance(), res["balance"] + 6_000)

    def test_second_building_adds_income(self):
        self.build("farm", 8, 10)
        self.build("mine", 8, 30)
        self.now += DAY + 5
        w = game_server.wallet("alice")[1]
        self.assertEqual(w["reports"][0]["buildings"], 2)
        self.assertEqual(w["reports"][0]["profit"], 12_000 + 30_000)

    def test_ledger_stays_balanced(self):
        self.build("farm", 8, 10)
        self.build("factory", 8, 30)
        self.now += DAY * 3 + 5
        game_server.wallet("alice")
        with game_server.connect() as db:
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
            negative = db.execute("SELECT 1 FROM wallets WHERE account LIKE 'player:%' AND balance<0").fetchall()
        self.assertEqual((bad, total, negative), ([], 0, []))

    def test_upkeep_never_creates_debt(self):
        broken = {"farm": {"product": "honey", "output": 1, "jobs": 4, "upkeep": 500_000}}
        self.build()
        with mock.patch.dict(economy.PRODUCTION, broken, clear=False):
            with game_server.connect() as db:
                db.execute("UPDATE wallets SET balance=1000 WHERE account='player:alice'")
            self.now += DAY + 5
            w = game_server.wallet("alice")[1]
        self.assertGreaterEqual(w["balance"], 0)

    def test_legacy_buildings_start_producing(self):
        self.build()
        with game_server.connect() as db:
            db.execute("DELETE FROM building_ops")
            db.execute("DELETE FROM company_state")
        self.now += DAY * 2 + 5     # legacy rows are registered on first contact (month index 2 here)
        before = self.balance()
        self.now += DAY * 2
        self.assertEqual(self.balance(), before + 2 * 12_000)

    def test_other_players_are_independent(self):
        self.build("farm", 8, 10, "alice")
        self.now += DAY + 5
        self.assertEqual(self.balance("bob"), 1_000_000)


if __name__ == "__main__":
    unittest.main()
