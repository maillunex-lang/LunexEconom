"""Проверки V2-DEMAND-DESIGN: данные, детерминизм, миграция, целые и устойчивость."""
from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from tools.sim.demand_layers import load_inputs, migrate_shares, rebuild_golden, run
from tools.sim.demand_layers.model import _income, _matrix_population

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "tools" / "sim" / "data" / "demand_proposed"


class DemandDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles, cls.cities, cls.params, cls.products = load_inputs()
        cls.report = run(24)

    def test_all_41_skus_and_12_baskets(self):
        all_ids = {p["id"] for p in self.products}
        consumer = {p["id"] for p in self.products if p["consumer"]}
        self.assertEqual(len(all_ids), 41)
        self.assertEqual(len(consumer), 20)
        self.assertEqual(len(self.profiles["baskets"]), 12)
        for profile in self.profiles["baskets"]:
            basket = profile["shares_permille"]
            self.assertEqual(set(basket), all_ids)
            self.assertEqual(sum(basket.values()), 1000)
            self.assertTrue(all(basket[id] == 0 for id in all_ids - consumer))
            self.assertTrue(all(type(v) is int and v >= 0 for v in basket.values()))
            if profile["layer"] == "poor":
                for premium in ("car", "electronics", "appliances", "furniture", "mead"):
                    self.assertEqual(basket[premium], 0)

    def test_ages_actually_differ(self):
        middle = {p["age"]: p["shares_permille"] for p in self.profiles["baskets"] if p["layer"] == "middle"}
        self.assertGreater(middle["youth"]["mead"], middle["pensioners"]["mead"])
        self.assertGreater(middle["pensioners"]["smoked_fish"], middle["youth"]["smoked_fish"])
        self.assertGreater(middle["pensioners"]["kefir"], middle["youth"]["kefir"])
        affluent = {p["layer"]: p["shares_permille"] for p in self.profiles["baskets"] if p["age"] == "families"}
        self.assertGreater(affluent["affluent"]["car"], affluent["middle"]["car"])

    def test_income_sources_and_city_mix(self):
        layers = {p["id"]: p for p in self.profiles["layers"]}
        ages = {p["id"]: p for p in self.profiles["ages"]}
        for city in self.cities["cities"]:
            self.assertEqual(sum(city["income_shares_bp"].values()), 10000)
            self.assertEqual(sum(city["age_shares_bp"].values()), 10000)
            allocated = _matrix_population(city["population"], city["income_shares_bp"], city["age_shares_bp"])
            self.assertEqual(sum(allocated.values()), city["population"])
            for layer in layers.values():
                for age in ages.values():
                    self.assertGreater(_income(layer, age, city, self.params), 0)

    def test_migration_is_bounded_and_conservative(self):
        shares = {"poor": 4000, "lower_middle": 3000, "middle": 2000, "affluent": 1000}
        for signal in (750, 1000, 1250):
            after = migrate_shares(shares, signal, self.params)
            self.assertEqual(sum(after.values()), 10000)
            self.assertTrue(all(v >= 0 for v in after.values()))
            self.assertLessEqual(abs(shares["poor"] - after["poor"]), self.params["monthly_migration_cap_bp"])
            self.assertLessEqual(abs(shares["affluent"] - after["affluent"]), self.params["monthly_migration_cap_bp"])
        self.assertEqual(migrate_shares(shares, 1000, self.params), shares)
        self.assertLess(migrate_shares(shares, 1250, self.params)["poor"], shares["poor"])
        self.assertGreater(migrate_shares(shares, 750, self.params)["poor"], shares["poor"])

    def test_legacy_m1_import_still_works(self):
        from tools.sim.demand import market_demand
        self.assertTrue(callable(market_demand))

    def test_goldens_deterministic(self):
        expected = json.loads((DATA / "golden_24_months.json").read_text(encoding="utf-8"))
        self.assertEqual(self.report, expected)
        self.assertEqual(self.report, run(24))
        self.assertEqual(set(self.report["cities"]), {"industrial", "resort", "administrative", "rural"})

    def test_24_monthly_conservation_and_stability(self):
        for city_id, result in self.report["cities"].items():
            with self.subTest(city=city_id):
                history = result["history"]
                self.assertEqual(len(history), 24)
                self.assertEqual(result["population_initial"], result["population_final"])
                self.assertGreater(result["minimum_retail_revenue_rub"], 0)
                self.assertLess(result["maximum_poor_share_bp"], 8000)
                self.assertGreater(result["last"]["inflation_index_permille"], 0)
                for row in history:
                    self.assertEqual(sum(row["income_shares_bp"].values()), 10000)
                    self.assertEqual(row["wanted_units"], sum(row["wanted_units_by_sku"].values()))
                    self.assertEqual(row["shortage_units"], sum(row["shortage_units_by_sku"].values()))
                    self.assertEqual(row["surplus_units"], sum(row["surplus_units_by_sku"].values()))
                    self.assertEqual(sum(row["retail_revenue_by_layer_rub"].values()), row["retail_revenue_rub"])
                    self.assertEqual(row["wanted_units"] - row["sold_units"], row["shortage_units"])
                    self.assertGreater(row["household_income_rub"], row["savings_rub"])
                    self.assertGreater(row["retail_revenue_rub"], 0)
                for left, right in zip(history, history[1:]):
                    self.assertLessEqual(abs(right["poor_share_bp"] - left["poor_share_bp"]), self.params["monthly_migration_cap_bp"])

    def test_integral_data_and_source(self):
        def recursive(value):
            if isinstance(value, dict):
                for child in value.values():
                    recursive(child)
            elif isinstance(value, list):
                for child in value:
                    recursive(child)
            else:
                self.assertTrue(type(value) in (int, bool, str, type(None)), value)
        recursive(self.report)
        recursive(self.profiles)
        recursive(self.cities)
        recursive(self.params)
        for source in (ROOT / "tools/sim/demand_layers").glob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                self.assertFalse(isinstance(node, ast.Constant) and isinstance(node.value, float))
                self.assertFalse(isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and not (isinstance(node.right, ast.Constant) and isinstance(node.right.value, str)))
        with self.assertRaises(ValueError):
            run(2)


if __name__ == "__main__":
    unittest.main()
