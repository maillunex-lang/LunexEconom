"""Reach model invariants and deterministic golden scenarios."""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import unittest
from pathlib import Path

from tools.sim.districts import split_largest_remainder
from tools.sim.reach import allocate_day, anchors, config, daily_capacity, falloff, fame_and_reputation, radius, reputation_score, simulate_reach

ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT / "tools" / "sim"
SCENARIOS = ("reach_corner_vs_mall", "reach_two_neighbors", "reach_far_stores", "reach_fame_growth", "reach_stockout", "reach_queue")


def scenario(name: str) -> dict:
    return json.loads((SIM / "scenarios" / "reach" / (name + ".json")).read_text(encoding="utf-8"))


def canonical(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class ReachGoldenTests(unittest.TestCase):
    def test_golden_and_conservation_for_all_scenarios(self):
        for name in SCENARIOS:
            with self.subTest(name=name):
                source = scenario(name)
                before = canonical(source)
                first = simulate_reach(source)
                second = simulate_reach(source)
                golden = json.loads((SIM / "golden" / "reach" / (name + ".json")).read_text(encoding="utf-8"))
                self.assertEqual(first, second)
                self.assertEqual(first, golden)
                self.assertEqual(before, canonical(source))
                self.assertEqual(first["totals"]["demand"], first["totals"]["allocated"] + first["totals"]["city"])
                for day in first["days"]:
                    self.assertEqual(day["demand"], sum(d["demand"] for d in day["districts"]))
                    self.assertEqual(day["allocated"] + day["city"], day["demand"])
                    self.assertEqual(day["sold"] + day["unserved"], day["allocated"])
                    for district in day["districts"]:
                        self.assertEqual(district["demand"], district["city"] + district["allocated_to_stores"])
                    for row in day["stores"]:
                        self.assertLessEqual(row["sold"], row["capacity_visitors"])
                        self.assertLessEqual(row["sold"], row["allocated"])

    def test_symmetry_identical_neighbors(self):
        first = simulate_reach(scenario("reach_two_neighbors"))["days"][0]
        stores = first["stores"]
        self.assertLessEqual(abs(stores[0]["allocated"] - stores[1]["allocated"]), len(first["districts"]) * 4)
        self.assertEqual(stores[0]["sold"], stores[1]["sold"])

    def test_far_store_does_not_change_other_district(self):
        case = scenario("reach_far_stores")
        both = simulate_reach(case)["days"][0]
        north = copy.deepcopy(case)
        north["stores"] = [north["stores"][0]]
        single = simulate_reach(north)["days"][0]
        self.assertEqual(both["stores"][0]["district_allocated"]["vokzalny_krug"], single["stores"][0]["district_allocated"]["vokzalny_krug"])
        self.assertEqual(both["stores"][0]["sold"], single["stores"][0]["sold"])
        self.assertEqual(both["stores"][0]["district_allocated"].get("yuzhnaya_okraina", 0), 0)

    def test_fame_grows_and_stockout_punishes(self):
        good = simulate_reach(scenario("reach_fame_growth"))["days"]
        bad = simulate_reach(scenario("reach_stockout"))["days"]
        self.assertGreater(good[-1]["stores"][0]["fame_after_permille"], good[0]["stores"][0]["fame_after_permille"])
        self.assertGreater(good[-1]["stores"][0]["reputation_after_permille"], good[0]["stores"][0]["reputation_after_permille"])
        self.assertLess(bad[-1]["stores"][0]["reputation_after_permille"], bad[0]["stores"][0]["reputation_after_permille"])
        self.assertEqual(bad[-1]["stores"][0]["sold"], 0)

    def test_queue_restricts_sales(self):
        day = simulate_reach(scenario("reach_queue"))["days"][0]
        row = day["stores"][0]
        self.assertGreater(row["allocated"], row["capacity_visitors"])
        self.assertGreater(row["queue_penalty_permille"], 0)
        self.assertLess(row["sold"], row["capacity_visitors"])

    def test_monotonic_area_quality_and_distance(self):
        params = config()
        obj = {"format": "corner", "area_m2": 40, "fame_permille": 300, "cashiers": 2}
        small = radius(obj, params)
        obj["area_m2"] = 400
        self.assertGreaterEqual(radius(obj, params), small)
        self.assertGreater(daily_capacity(obj, params), 0)
        self.assertLessEqual(falloff(small + 1, small, params), falloff(2, small, params))
        low = reputation_score(30, 90, 90, 1000)
        high = reputation_score(95, 90, 90, 1000)
        self.assertGreaterEqual(high, low)
        state = {"fame_permille": 100, "reputation_permille": 500, "days_with_sales": 5, "ad_spend_rub": 0, "ad_reach_permille": 0, "quality": 30, "price": 90, "stock_availability_permille": 1000, "day": 1}
        a = fame_and_reputation(state, params, 100, 100)
        state["quality"] = 95
        b = fame_and_reputation(state, params, 100, 100)
        self.assertGreaterEqual(b["reputation_permille"], a["reputation_permille"])

    def test_no_floats_or_true_division_and_rejects_overflow_inputs(self):
        for file in (SIM / "reach.py", SIM / "__main__.py"):
            tree = ast.parse(file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                self.assertFalse(isinstance(node, ast.Constant) and isinstance(node.value, float))
                self.assertFalse(isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and not (isinstance(node.right, ast.Constant) and isinstance(node.right.value, str)))
        payload = canonical(simulate_reach(scenario("reach_queue")))
        json.loads(payload, parse_float=lambda _: self.fail("float in report"))
        self.assertEqual(split_largest_remainder(101, [1, 1], ["a", "b"]), [51, 50])
        obj = scenario("reach_queue")
        obj["stores"][0]["area_m2"] = True
        with self.assertRaises(ValueError):
            simulate_reach(obj)
