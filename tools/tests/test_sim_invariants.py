"""Инварианты симулятора: журнал, целые числа, формулы из документов."""
from __future__ import annotations

import ast
import hashlib
import json
import unittest
from pathlib import Path

from tools.sim.catalog import Catalog, repo_root
from tools.sim.engine import load_scenario, simulate
from tools.sim.formulas import demand_units, load_bp, split_by_bp, vat_on_gross
from tools.sim.ledger import Ledger


ROOT = repo_root()
SIM = ROOT / "tools" / "sim"


def canonical(report: dict) -> str:
    raw = json.dumps(report, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class LedgerTests(unittest.TestCase):
    def test_rejects_unbalanced_line(self):
        ledger = Ledger()
        with self.assertRaises(RuntimeError):
            ledger.post("bad", [("player:a", 10), ("system:treasury", -5)])

    def test_player_cannot_go_negative_and_repeat_is_idempotent(self):
        ledger = Ledger()
        first = ledger.post("seed", [("player:a", 10), ("system:treasury", -10)])
        again = ledger.post("seed", [("player:a", 10), ("system:treasury", -10)])
        self.assertEqual(first, again)
        self.assertEqual(ledger.balance("player:a"), 10)
        self.assertIsNone(ledger.post("over", [("player:a", -11), ("system:treasury", 11)]))
        self.assertEqual(ledger.balance("player:a"), 10)
        ledger.audit()


class FormulaTests(unittest.TestCase):
    def test_population_example_one_layer(self):
        # docs/proposals/07_POPULATION.md, пример среднего слоя центра Уфы.
        demand = demand_units(207000, 2, 400, 1000, 90, 90, 1, 70, 1000)
        self.assertEqual(demand, 150696)

    def test_price_plus_ten_percent_lowers_sensitivity(self):
        base = demand_units(207000, 2, 400, 1000, 90, 90, 1, 70, 1000)
        higher = demand_units(207000, 2, 400, 1000, 99, 90, 1, 70, 1000)
        self.assertLess(higher, base)
        self.assertEqual(higher, 150696 * 990 // 1000)

    def test_mill_half_stock_is_half_load(self):
        catalog = Catalog()
        recipe = catalog.recipe_for("mill_flour")
        volume = int(recipe["inputs"]["grain"])
        have = volume // 2
        capacity = int(catalog.building("mill")["storage_capacity"])
        load = load_bp({"grain": {"quantity": have, "quality": 50}}, recipe, capacity, 10000)
        self.assertEqual(load, have * 10000 // volume)
        self.assertEqual(load, 5000)

    def test_vat_included_in_shelf_price(self):
        gross = 9000
        base = gross * 10000 // 11000
        self.assertEqual(vat_on_gross(gross), gross - base)
        self.assertEqual(vat_on_gross(gross), 819)

    def test_stage_shares_sum_to_build_cost(self):
        catalog = Catalog()
        cost = int(catalog.building("bakery")["build_cost"])
        parts = split_by_bp(cost, (3000, 4000, 2000, 1000))
        self.assertEqual(sum(parts), cost)
        self.assertEqual(parts, [cost * 3000 // 10000, cost * 7000 // 10000 - cost * 3000 // 10000, cost * 9000 // 10000 - cost * 7000 // 10000, cost - cost * 9000 // 10000])


class SourceTests(unittest.TestCase):
    def test_simulator_uses_no_float_division_or_random(self):
        for path in sorted(SIM.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                    self.fail(f"деление / в {path}")
                if isinstance(node, ast.Constant) and isinstance(node.value, float):
                    self.fail(f"дробный литерал в {path}")
                if isinstance(node, ast.Name) and node.id in {"float", "Decimal", "random"}:
                    self.fail(f"{node.id} в {path}")
                if isinstance(node, ast.Attribute) and node.attr == "random":
                    self.fail(f"random в {path}")


class DeterminismTests(unittest.TestCase):
    def test_two_runs_share_a_hash(self):
        scenario = load_scenario(SIM / "scenarios" / "m1_basic.json")
        first = canonical(simulate(scenario))
        second = canonical(simulate(scenario))
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)


if __name__ == "__main__":
    unittest.main()
