import json
import unittest
from tools.sim.ai_engine import model


class AiEngineSim(unittest.TestCase):
    def setUp(self):
        self.p, self.s = model.load()
        self.r = {x["id"]: x for x in model.run_all()["scenarios"]}

    def test_golden_reproducible(self):
        self.assertEqual(model.run_all(), json.loads((model.DATA / "golden.json").read_text(encoding="utf-8")))

    def test_integers_only(self):
        def walk(x):
            if isinstance(x, dict):
                [walk(v) for v in x.values()]
            elif isinstance(x, list):
                [walk(v) for v in x]
            elif not isinstance(x, str):
                self.assertIs(type(x), int)
        walk(model.run_all())

    def test_ai_does_not_outearn_humans_unfairly(self):
        for sid in ("with_balanced_ai", "with_aggressive_ai"):
            self.assertLessEqual(self.r[sid]["ai_to_human_profit_bp"], self.p["ai_profit_cap_bp_of_human"])

    def test_market_share_cap(self):
        for x in self.r.values():
            self.assertLessEqual(x["ai_share_end_bp"], self.p["max_market_share_bp"])

    def test_dumping_below_cost_is_bounded(self):
        scn = dict(self.s["scenarios"][3], months=self.s["months"])
        pl = scn["players"][2]
        below, forced = 0, 0
        for _ in range(self.s["months"]):
            price, wants = model.price_of(pl, scn["unit_cost"], self.p, below)
            if price < scn["unit_cost"]:
                forced += 1
            below = below + 1 if wants else 0
        self.assertLessEqual(forced, self.p["max_below_cost_months"])

    def test_dumper_loses_when_cost_high(self):
        self.assertLess(self.r["with_dumper_high_cost"]["profits"][2], self.r["with_dumper_high_cost"]["profits"][0])


if __name__ == "__main__":
    unittest.main()
