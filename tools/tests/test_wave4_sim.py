import json
import unittest
from tools.sim.wave4 import model


class Wave4(unittest.TestCase):
    def setUp(self):
        self.p = model.load()
        self.r = model.run_all()

    def test_golden_reproducible(self):
        self.assertEqual(self.r, json.loads((model.DATA / "golden.json").read_text(encoding="utf-8")))

    def test_integers_only(self):
        def walk(x):
            if isinstance(x, dict):
                [walk(v) for v in x.values()]
            elif isinstance(x, list):
                [walk(v) for v in x]
            elif not isinstance(x, str):
                self.assertIs(type(x), int)
        walk(self.r)

    def test_brand_diminishing_and_bounded(self):
        b = self.r["brand"]
        self.assertTrue(all(0 <= x["final_brand_bp"] <= 10000 for x in b))
        self.assertGreater(b[2]["final_brand_bp"], b[1]["final_brand_bp"])
        self.assertLess(b[2]["final_brand_bp"] - b[1]["final_brand_bp"], 2 * b[1]["final_brand_bp"])

    def test_mid_ad_budget_beats_none_and_overspend(self):
        b = self.r["brand"]
        self.assertGreater(b[1]["profit"], b[0]["profit"])
        self.assertGreater(b[1]["profit"], b[2]["profit"])

    def test_stock_ipo_conserves_founder_share(self):
        s = self.r["stock"]
        self.assertEqual(s["founder_share_bp"] + self.p["stock"]["ipo_share_bp"], 10000)
        self.assertLess(s["ipo_price_x100"], s["valuation"] * 100 // self.p["stock"]["shares"])

    def test_trade_corridor_holds(self):
        t = self.r["trade"]
        for row in t["rows"]:
            self.assertTrue(t["export_price"] <= row["effective"] <= t["import_price"])

    def test_events_reduce_profit(self):
        self.assertLess(self.r["events"]["with_events"], self.r["events"]["calm"])

    def test_own_truck_pays_back_faster_with_distance(self):
        pb = [x["payback_months"] for x in self.r["logistics"] if x["payback_months"]]
        self.assertEqual(pb, sorted(pb, reverse=True))

    def test_service_capacity_limits_sales(self):
        s = self.r["service"]
        self.assertTrue(all(x["sold"] <= x["capacity"] for x in s))
        self.assertEqual(s[-1]["sold"], s[-1]["capacity"])


if __name__ == "__main__":
    unittest.main()
