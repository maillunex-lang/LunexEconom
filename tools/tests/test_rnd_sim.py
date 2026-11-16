import json
import unittest
from tools.sim.rnd import model


class RndSim(unittest.TestCase):
    def setUp(self):
        self.p, self.s = model.load()

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

    def test_prerequisites_respected(self):
        for v in model.run_all()["variants"]:
            order = sorted(v["unlock_month"], key=lambda k: v["unlock_month"][k])
            nodes = {n["id"]: n for n in self.p["tech_nodes"]}
            for nid, month in v["unlock_month"].items():
                for req in nodes[nid]["requires"]:
                    self.assertLessEqual(v["unlock_month"][req], month)

    def test_staff_level_speeds_research(self):
        self.assertGreater(model.rp_month(20000, 3, self.p), model.rp_month(20000, 1, self.p))

    def test_license_costs_at_least_replacement_cost(self):
        v = next(x for x in model.run_all()["variants"] if x["id"] == "licensed")
        replacement = sum(n["cost_rp"] * 1000 // self.p["rp_per_1000_rub"] for n in self.p["tech_nodes"] if n["id"] in v["tech_done"])
        self.assertGreaterEqual(v["license_fee"], replacement)

    def test_obsolescence_bounded(self):
        for _, f in model.run_all()["obsolescence"]:
            self.assertTrue(self.p["obsolescence"]["floor_bp"] <= f <= 10000)

    def test_rnd_beats_none(self):
        r = {v["id"]: v for v in model.run_all()["variants"]}
        self.assertGreater(r["rnd_small"]["profit"], r["no_rnd"]["profit"])


if __name__ == "__main__":
    unittest.main()
