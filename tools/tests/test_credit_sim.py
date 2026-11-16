import json
import unittest
from tools.sim.credit import model


class CreditSim(unittest.TestCase):
    def setUp(self):
        self.p, self.s = model.load()

    def test_golden_reproducible(self):
        self.assertEqual(model.run_all(), json.loads((model.DATA / "golden.json").read_text(encoding="utf-8")))

    def test_integers_only(self):
        for v in model.run_all()["variants"]:
            for k, x in v.items():
                if k != "id":
                    self.assertIs(type(x), int)

    def test_schedule_repays_principal_exactly(self):
        rows = model.schedule(200000, 24, 183)
        self.assertEqual(sum(r[1] for r in rows), 200000)
        self.assertEqual(len(rows), 24)
        self.assertTrue(all(r[2] >= 0 for r in rows))

    def test_rating_spread_monotonic(self):
        r = [model.rate_bp_month(k, self.p) for k in "ABCD"]
        self.assertEqual(r, sorted(r))

    def test_rating_letter_bounds(self):
        self.assertEqual(model.rating_letter(900, self.p), "A")
        self.assertEqual(model.rating_letter(100, self.p), "D")

    def test_loan_costs_interest_and_pays_off_vs_none(self):
        r = {v["id"]: v for v in model.run_all()["variants"]}
        self.assertGreater(r["expand_with_loan"]["interest_total"], 0)
        self.assertGreater(r["expand_with_loan"]["net_cash_end"], r["no_expansion"]["net_cash_end"])
        self.assertGreater(r["expand_with_cash"]["net_cash_end"], r["expand_with_loan"]["net_cash_end"] - 1)

    def test_shock_triggers_seizure(self):
        r = {v["id"]: v for v in model.run_all()["variants"]}
        self.assertGreater(r["loan_income_shock"]["seized_month"], 0)


if __name__ == "__main__":
    unittest.main()
