"""BE-107: grain field → elevator → mill → bread plant → shop, without breaking the old trio."""
import os
import tempfile
import unittest
import uuid
from unittest import mock

import game_server
import economy

DAY = 86400
T0 = 1_800_000_000


def rid():
    return str(uuid.uuid4())


class AgroBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = game_server.DB
        game_server.DB = os.path.join(self.tmp.name, "w.sqlite3")
        self.now = T0
        patch = mock.patch.object(game_server.time, "time", side_effect=lambda: self.now)
        patch.start()
        self.addCleanup(patch.stop)
        self.cursor = 0

    def tearDown(self):
        game_server.DB = self.old
        self.tmp.cleanup()

    def build(self, who, kind):
        for _ in range(400):
            self.cursor += 1
            status, res = game_server.build(who, {"kind": kind, "x": 2, "y": 2 + 4 * self.cursor, "request_id": rid()})
            if status == 201:
                return res
            self.assertIn(res.get("error"), ("water", "road_overlap", "occupied", "no_road_access"), res)
        self.fail("no free site for %s" % kind)

    def grant(self, who, amount):
        game_server.wallet(who)
        with game_server.connect() as db:
            db.execute("UPDATE wallets SET balance=balance+? WHERE account=?", (amount, economy.player_account(who)))
            db.execute("UPDATE wallets SET balance=balance-? WHERE account=?", (amount, economy.TREASURY))

    def month(self, who, n=1):
        self.now += DAY * n + 5
        return game_server.wallet(who)[1]

    def price_row(self, product, month):
        with game_server.connect() as db:
            return db.execute(
                "SELECT price,supply,demand FROM market_prices WHERE product=? AND month_index=?",
                (product, month)).fetchone()

    def assert_ledger(self):
        with game_server.connect() as db:
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
            negative = db.execute("SELECT 1 FROM wallets WHERE account LIKE 'player:%' AND balance<0").fetchall()
        self.assertEqual((bad, total, negative), ([], 0, []))


class AgroChainTests(AgroBase):
    def test_integrated_chain_sells_bread_and_keeps_inputs_inside(self):
        for kind in ("grain_field", "elevator", "mill", "bread_plant", "shop"):
            self.build("alice", kind)
        wallet = self.month("alice")
        self.assertEqual(wallet["inventory"]["capacity"], 600)
        bread = self.price_row("bread", 0)
        grain = self.price_row("grain", 0)
        flour = self.price_row("flour", 0)
        self.assertIsNotNone(bread)
        self.assertGreater(bread[1], 0)
        self.assertEqual(grain[1], 0)     # the mill ate the harvest
        self.assertEqual(flour[1], 0)     # the bread plant ate the flour
        report = wallet["reports"][0]
        self.assertEqual(report["input_cost"], 0)
        self.assertGreater(report["revenue"], bread[1] * bread[0])  # shop markup on top of wholesale bread
        self.assert_ledger()

    def test_chain_across_companies(self):
        self.build("alice", "grain_field")
        self.build("bob", "mill")
        self.build("carol", "bread_plant")
        self.build("dave", "shop")
        alice, bob, carol, dave = (self.month(who) for who in ("alice", "bob", "carol", "dave"))
        self.assertGreater(self.price_row("grain", 0)[1], 0)
        self.assertGreater(bob["reports"][0]["input_cost"], 0)
        self.assertGreater(self.price_row("bread", 0)[1], 0)
        self.assertGreater(carol["reports"][0]["revenue"], 0)
        self.assertGreater(dave["reports"][0]["revenue"], 0)
        self.assert_ledger()
        self.assertGreater(alice["reports"][0]["revenue"], 0)

    def test_a_hungry_mill_does_not_stop_the_old_factory(self):
        self.grant("alice", 400_000)
        for kind in ("farm", "mine", "factory", "mill"):
            self.build("alice", kind)
        self.month("alice")
        honey, oil, goods = (self.price_row(p, 0)[1] for p in ("honey", "oil", "goods"))
        self.assertEqual((honey, oil, goods), (80, 30, 60))
        self.assertEqual(self.price_row("flour", 0)[1], 0)
        self.assert_ledger()

    def test_old_world_still_publishes_exactly_three_prices(self):
        self.build("alice", "farm")
        self.build("bob", "mine")
        self.build("carol", "factory")
        self.month("alice")
        with game_server.connect() as db:
            products = [row[0] for row in db.execute("SELECT product FROM market_prices WHERE month_index=0 ORDER BY product")]
        self.assertEqual(products, ["goods", "honey", "oil"])


if __name__ == "__main__":
    unittest.main()
