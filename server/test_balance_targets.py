import os
import sys
import unittest

import balance_targets as bt


class BalanceTargetsTests(unittest.TestCase):
    def test_corridors_are_well_formed(self):
        for name, (low, high, unit, status, source) in bt.CORRIDORS.items():
            self.assertLess(low, high, name)
            self.assertIn(status, ("measured", "planned"), name)
            self.assertTrue(unit and source, name)

    def test_measured_corridors_point_at_real_simulator_metrics(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
        import balance_sim
        fields = set(balance_sim.CSV_FIELDS)
        for name, (low, high, unit, status, source) in bt.CORRIDORS.items():
            if status == "measured":
                self.assertTrue(source in fields or source == "*_price", (name, source))

    def test_invariants_are_simulator_fields(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
        import balance_sim
        for name in bt.INVARIANTS:
            self.assertIn(name, balance_sim.METRIC_FIELDS)

    def test_check_reports_only_indicators_outside_the_corridor(self):
        self.assertEqual(bt.check({"unemployment": 0.06, "price_vs_reference": 1.0}), [])
        self.assertEqual(bt.check({"unemployment": 0.5, "unknown": 9}), [("unemployment", 0.5, 0.03, 0.12)])


if __name__ == "__main__":
    unittest.main()
