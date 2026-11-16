import json
import unittest
from tools.sim.staff import model


class StaffSim(unittest.TestCase):
    def setUp(self):
        self.p, self.s = model.load()

    def test_golden_reproducible(self):
        self.assertEqual(model.run_all(), json.loads((model.DATA / "golden.json").read_text(encoding="utf-8")))

    def test_integers_only(self):
        for v in model.run_all()["variants"]:
            for key, value in v.items():
                if key != "id":
                    self.assertIs(type(value), int)

    def test_productivity_monotonic(self):
        values = [model.productivity_bp(l, self.p) for l in range(1, 10)]
        self.assertEqual(values, sorted(values))

    def test_level_cost_grows_quadratically(self):
        self.assertEqual(model.level_up_cost(2, self.p), 4 * model.level_up_cost(1, self.p))

    def test_underpay_raises_turnover_and_hurts_morale(self):
        e = model.expected_wage(1, self.p)
        self.assertGreater(model.turnover_bp(e * 7 // 10, 1, self.p), model.turnover_bp(e, 1, self.p))
        self.assertLess(model.morale_bp(e * 7 // 10, 1, self.p), model.morale_bp(e, 1, self.p))

    def test_low_wage_worse_than_market(self):
        r = {v["id"]: v for v in model.run_all()["variants"]}
        self.assertLess(r["low_wage"]["profit"], r["market_wage_no_training"]["profit"])
        self.assertGreater(r["low_wage"]["quits"], r["market_wage_no_training"]["quits"])

    def test_training_raises_level(self):
        r = {v["id"]: v for v in model.run_all()["variants"]}
        self.assertGreater(r["market_wage_training"]["final_level"], r["market_wage_no_training"]["final_level"])


if __name__ == "__main__":
    unittest.main()
