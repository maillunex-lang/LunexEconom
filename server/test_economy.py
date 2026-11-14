import os
import tempfile
import unittest
import uuid

import economy
import game_server


def rid():
    return str(uuid.uuid4())


class EconomyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = game_server.DB
        game_server.DB = os.path.join(self.tmp.name, "w.sqlite3")

    def tearDown(self):
        game_server.DB = self.old
        self.tmp.cleanup()

    def build(self, kind, x, y, who="alice", request_id=None):
        return game_server.build(who, {"kind": kind, "x": x, "y": y, "request_id": request_id or rid()})

    def ledger_sums(self):
        with game_server.connect() as db:
            bad = db.execute("SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall()
            total = db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
        return bad, total

    def test_terms(self):
        t = economy.terms()
        self.assertEqual(t["start_capital"], 1_000_000)
        self.assertEqual(t["building_costs"], {"farm": 120_000, "mine": 300_000, "factory": 450_000, "warehouse": 80_000,
                                                  "shop": 160_000,
                                                  "school": 400_000, "hospital": 800_000, "park": 150_000})
        self.assertEqual(t["road_cell_cost"], 5_000)

    def test_wallet_starts_with_capital_once(self):
        status, w = game_server.wallet("alice")
        self.assertEqual((status, w["balance"]), (200, 1_000_000))
        self.assertEqual(game_server.wallet("alice")[1]["balance"], 1_000_000)
        self.assertEqual(len(w["transactions"]), 1)
        self.assertEqual(w["transactions"][0]["kind"], "start_capital")

    def test_build_charges_building_and_road(self):
        status, res = self.build("farm", 8, 10)
        self.assertEqual(status, 201, res)
        expected = 120_000 + 5_000 * res["road_cells"]
        self.assertEqual(res["cost"], expected)
        self.assertEqual(res["balance"], 1_000_000 - expected)
        self.assertEqual(game_server.wallet("alice")[1]["balance"], res["balance"])
        bad, total = self.ledger_sums()
        self.assertEqual(bad, [])
        self.assertEqual(total, 0)  # money is only moved, never created outside the treasury

    def test_idempotent_replay_does_not_charge_twice(self):
        r = rid()
        s1, a = self.build("farm", 8, 10, request_id=r)
        s2, b = self.build("farm", 8, 10, request_id=r)
        self.assertEqual((s1, s2, a, b), (201, 200, a, a))
        self.assertEqual(game_server.wallet("alice")[1]["balance"], a["balance"])

    def test_insufficient_funds_has_no_side_effects(self):
        # two factories fit into 1,000,000 only with short roads; build until the money runs out
        results = []
        x = 8
        for i in range(6):
            results.append(self.build("factory", x, 10 + i * 6))
        statuses = [s for s, _ in results]
        self.assertIn(402, statuses)
        failed = next(r for s, r in results if s == 402)
        self.assertEqual(failed["error"], "insufficient_funds")
        self.assertGreater(failed["cost"], failed["balance"])
        balance = game_server.wallet("alice")[1]["balance"]
        self.assertEqual(balance, failed["balance"])
        self.assertGreaterEqual(balance, 0)
        with game_server.connect() as db:
            buildings = db.execute("SELECT COUNT(*) FROM buildings").fetchone()[0]
        self.assertEqual(buildings, statuses.count(201))

    def test_wallets_are_per_player(self):
        self.build("farm", 8, 10, who="alice")
        self.assertEqual(game_server.wallet("bob")[1]["balance"], 1_000_000)

    def test_unbalanced_ledger_rejected(self):
        with game_server.connect() as db:
            with self.assertRaises(ValueError):
                economy.post(db, "?", "x", "x", [("a", 5), ("b", -4)], 0)


if __name__ == "__main__":
    unittest.main()
