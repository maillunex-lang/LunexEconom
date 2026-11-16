import json
import unittest
from tools.sim.objects import model


class ObjectsSim(unittest.TestCase):
    def setUp(self):
        self.p, self.s = model.load()

    def test_golden_reproducible(self):
        golden = json.loads((model.DATA / "golden.json").read_text(encoding="utf-8"))
        self.assertEqual(model.run_all(), golden)

    def test_all_integers(self):
        def walk(x):
            if isinstance(x, dict):
                [walk(v) for v in x.values()]
            elif isinstance(x, list):
                [walk(v) for v in x]
            elif not isinstance(x, str):
                self.assertIs(type(x), int)
        walk(model.run_all())

    def test_wear_monotonic_without_repair(self):
        r = model.run_wear(self.s["wear"], self.s["wear"]["variants"][0], self.p)
        wears = [row[1] for row in r["months"]]
        self.assertEqual(wears, sorted(wears))
        self.assertLessEqual(max(wears), 10000)

    def test_repair_resets_wear_and_costs_money(self):
        r = model.run_wear(self.s["wear"], self.s["wear"]["variants"][2], self.p)
        self.assertGreater(r["repair_spent"], 0)
        self.assertLess(r["final_wear_bp"], 3000)

    def test_repair_beats_no_repair(self):
        runs = {v["id"]: model.run_wear(self.s["wear"], v, self.p) for v in self.s["wear"]["variants"]}
        self.assertGreater(runs["repair_at_3000"]["profit"], runs["no_repair"]["profit"])

    def test_deposit_never_negative_and_slows(self):
        r = model.run_deposit(self.s["deposit"], self.p)
        self.assertGreaterEqual(r["remaining"], 0)
        takes = [row[1] for row in r["months"]]
        self.assertLessEqual(takes[-1], takes[0])
        self.assertEqual(r["extracted"] + r["remaining"], self.s["deposit"]["initial_reserve"])

    def test_auto_buy_prevents_lost_input(self):
        manual, auto = (model.run_automation(self.s["automation"], a, self.p) for a in (False, True))
        self.assertGreater(manual["lost_input"], 0)
        self.assertEqual(auto["lost_input"], 0)
        self.assertGreater(auto["profit"], manual["profit"])


if __name__ == "__main__":
    unittest.main()
