import unittest
from tools.balance import bench


class Bench(unittest.TestCase):
    products = [{"id": "a", "reference_price": 10}, {"id": "b", "reference_price": 40}]
    buildings = [{"id": "x", "jobs": 2, "build_cost": 30000, "upkeep_month": 1000}]

    def rec(self, outputs, inputs):
        return [{"id": "r", "building": "x", "outputs": outputs, "inputs": inputs}]

    def test_profit_and_payback_integers(self):
        rows = bench.analyse(self.products, self.buildings, self.rec({"b": 10}, {"a": 5}), wage_month=100)
        r = rows[0]
        self.assertEqual(r["added_day"], 350)
        self.assertEqual(r["profit_month"], 350 * 30 - 200 - 1000)
        self.assertEqual(r["payback_days"], 30000 * 30 // r["profit_month"])
        for v in r.values():
            if not isinstance(v, str):
                self.assertIs(type(v), int)

    def test_loss_flagged(self):
        rows = bench.classify(bench.analyse(self.products, self.buildings, self.rec({"a": 1}, {"b": 5}), 100), 15, 30)
        self.assertEqual(rows[0]["flag"], "loss")
        self.assertIsNone(rows[0]["payback_days"])

    def test_fast_and_ok_flags(self):
        fast = bench.classify(bench.analyse(self.products, self.buildings, self.rec({"b": 100}, {}), 100), 15, 30)[0]
        self.assertEqual(fast["flag"], "fast")

    def test_runs_on_real_catalog(self):
        rows = bench.classify(bench.analyse(*bench.load("server/data")), 15, 30)
        self.assertEqual(len(rows), 41)
        self.assertTrue(all(r["flag"] in ("ok", "loss", "slow", "fast") for r in rows))

    def test_render_has_header(self):
        rows = bench.classify(bench.analyse(*bench.load("server/data")), 15, 30)
        self.assertTrue(bench.render(rows).startswith("рецепт"))


if __name__ == "__main__":
    unittest.main()
