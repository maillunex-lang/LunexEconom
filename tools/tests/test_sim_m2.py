"""Районы M2, четыре слоя, остаток деления и золотые прогоны."""
from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from tools.sim.catalog import Catalog
from tools.sim.demand import attractiveness, market_demand, reference_rating, sensitivity_rows
from tools.sim.districts import allocate_population, load_city_districts, split_largest_remainder, ufa_path
from tools.sim.engine import load_scenario, simulate
from tools.sim.formulas import demand_units


ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT / "tools" / "sim"


def _no_float(value, label: str) -> None:
    if isinstance(value, float):
        raise AssertionError(f"float в {label}")
    if isinstance(value, dict):
        for key, item in value.items():
            _no_float(item, f"{label}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _no_float(item, f"{label}[{index}]")


def _reject_float_text(text: str) -> None:
    json.loads(text, parse_float=lambda raw: (_ for _ in ()).throw(ValueError(raw)))


class DistrictDataTests(unittest.TestCase):
    def test_ufa_file_is_draft_integers_and_four_layers(self):
        text = ufa_path().read_text(encoding="utf-8")
        _reject_float_text(text)
        book = load_city_districts()
        self.assertEqual(book["balance"], "draft")
        self.assertEqual(book["city_id"], "ufa")
        self.assertEqual(len(book["layers"]), 4)
        self.assertEqual([row["id"] for row in book["layers"]], ["low", "mid", "high", "premium"])
        self.assertEqual(sum(row["pop_permille"] for row in book["districts"]), 1000)
        self.assertGreaterEqual(len(book["districts"]), 4)
        self.assertLessEqual(len(book["districts"]), 6)
        _no_float(book, "districts")

    def test_population_remainder_is_kept(self):
        book = load_city_districts()
        pops = allocate_population(1001, book["districts"])
        self.assertEqual(sum(pops), 1001)
        floors = [1001 * row["pop_permille"] // 1000 for row in book["districts"]]
        self.assertGreater(1001 - sum(floors), 0)
        self.assertEqual(sum(pops), sum(floors) + (1001 - sum(floors)))


class DemandTests(unittest.TestCase):
    def test_one_district_matches_current_formula(self):
        catalog = Catalog()
        product = catalog.product("bread")
        district = {
            "id": "ufa",
            "name": "Уфа",
            "type": "центр",
            "pop_permille": 1000,
            "traffic": 0,
            "appeal_permille": 1000,
            "layers_permille": {"only": 1000},
        }
        layers = [{"id": "only", "income_index_permille": 1000, "name": "один"}]
        stores = [
            {
                "enterprise": "store",
                "player": "mira",
                "slot": 1,
                "district": "ufa",
                "price": 90,
                "rating": 70,
                "traffic": 0,
                "appeal_permille": 1000,
            }
        ]
        report = market_demand(1150000, product, [district], layers, stores, 1, 1000)
        expected = demand_units(1150000, 2, 1000, 1000, 90, 90, 1, 70, 1000)
        self.assertEqual(report["demand"], expected)
        self.assertEqual(report["remainder"], 0)
        self.assertEqual(report["districts"][0]["stores"][0]["share"], expected)
        self.assertEqual(attractiveness(70, 0, 1000), 70)
        self.assertEqual(reference_rating(product), 70)

    def test_district_demands_sum_to_city_and_carry_remainder(self):
        catalog = Catalog()
        product = catalog.product("bread")
        layers = [{"id": "mid", "income_index_permille": 1000, "name": "средний"}]
        districts = []
        for index, permille in enumerate((333, 333, 334)):
            districts.append(
                {
                    "id": f"d{index}",
                    "name": f"d{index}",
                    "type": "жилой",
                    "pop_permille": permille,
                    "traffic": 0,
                    "appeal_permille": 1000,
                    "layers_permille": {"mid": 1000},
                }
            )
        found = False
        for population in range(2, 4000):
            report = market_demand(population, product, districts, layers, [], 2, 1000)
            self.assertEqual(sum(row["population"] for row in report["districts"]), population)
            self.assertEqual(sum(row["demand"] for row in report["districts"]), report["demand"])
            self.assertEqual(report["floor_demand"] + report["remainder"], report["demand"])
            self.assertGreaterEqual(report["remainder"], 0)
            if report["remainder"] > 0:
                found = True
                break
        self.assertTrue(found)

    def test_store_shares_sum_to_district_demand(self):
        catalog = Catalog()
        product = catalog.product("bread")
        book = load_city_districts()
        stores = [
            {
                "enterprise": "cheap",
                "player": "mira",
                "slot": 1,
                "district": "medovy_kvartal",
                "price": 90,
                "rating": 70,
                "traffic": 40,
                "appeal_permille": 1000,
            },
            {
                "enterprise": "dear",
                "player": "oleg",
                "slot": 1,
                "district": "medovy_kvartal",
                "price": 120,
                "rating": 60,
                "traffic": 40,
                "appeal_permille": 1000,
            },
        ]
        report = market_demand(
            1150000,
            product,
            book["districts"],
            book["layers"],
            stores,
            book["competition_s"],
            book["ad_factor_permille"],
        )
        _no_float(report, "demand")
        self.assertEqual(sum(row["demand"] for row in report["districts"]), report["demand"])
        self.assertEqual(sum(row["population"] for row in report["districts"]), 1150000)
        medovy = next(row for row in report["districts"] if row["id"] == "medovy_kvartal")
        shares = [store["share"] for store in medovy["stores"]]
        self.assertEqual(sum(shares), medovy["demand"])
        self.assertGreater(shares[0], shares[1])
        self.assertEqual(book["competition_s"], 2)
        weight_cheap = medovy["stores"][0]["weight"]
        weight_dear = medovy["stores"][1]["weight"]
        self.assertEqual(weight_cheap, medovy["stores"][0]["appeal"] * medovy["stores"][0]["appeal"])
        self.assertGreater(weight_cheap, weight_dear)

    def test_split_remainder_matches_total(self):
        parts = split_largest_remainder(10, [1, 1, 1], ["a", "b", "c"])
        self.assertEqual(sum(parts), 10)
        self.assertEqual(sorted(parts), [3, 3, 4])

    def test_sensitivity_grid_is_integral(self):
        rows = sensitivity_rows(207000, 2, 400, 1000, 90, 1, [90, 99, 270], [70])
        self.assertEqual(rows[0]["demand"], 150696)
        self.assertLess(rows[1]["demand"], rows[0]["demand"])
        self.assertEqual(rows[1]["demand"], 150696 * 990 // 1000)
        _no_float(rows, "sensitivity")


class EngineM2Tests(unittest.TestCase):
    def test_two_runs_and_goldens_and_no_floats(self):
        for path in sorted((SIM / "scenarios").glob("m2_*.json")):
            scenario = load_scenario(path)
            first = simulate(scenario)
            second = simulate(scenario)
            self.assertEqual(first, second)
            _no_float(first, path.name)
            _reject_float_text(json.dumps(first))
            golden = json.loads((SIM / "golden" / f"{path.stem}.json").read_text(encoding="utf-8"))
            self.assertEqual(first, golden)
            day = first["days"][0]
            self.assertIn("demand", day)
            demand = day["demand"][0]
            self.assertEqual(sum(row["demand"] for row in demand["districts"]), demand["demand"])
            self.assertEqual(demand["floor_demand"] + demand["remainder"], demand["demand"])
            for district in demand["districts"]:
                if district["stores"] and sum(store["weight"] for store in district["stores"]) > 0:
                    self.assertEqual(sum(store["share"] for store in district["stores"]), district["demand"])

    def test_m1_scenario_has_no_m2_block_and_matches_formula_path(self):
        report = simulate(load_scenario(SIM / "scenarios" / "m1_basic.json"))
        self.assertNotIn("demand", report["days"][0])
        self.assertNotIn("district", report["days"][0]["enterprises"]["store"])

    def test_income_shift_raises_rich_demand(self):
        report = simulate(load_scenario(SIM / "scenarios" / "m2_income_layers.json"))
        first = report["days"][0]["demand"][0]
        second = report["days"][1]["demand"][0]
        med_1 = next(row for row in first["districts"] if row["id"] == "medovy_kvartal")
        med_2 = next(row for row in second["districts"] if row["id"] == "medovy_kvartal")
        self.assertEqual(med_1["layers"][3]["share_permille"], 50)
        self.assertEqual(med_2["layers"][3]["share_permille"], 250)
        self.assertGreater(med_2["demand"], med_1["demand"])
        self.assertGreater(report["days"][1]["players"]["mira"]["sales"], 0)
        self.assertEqual(report["days"][0]["players"]["mira"]["sales"], med_1["stores"][0]["share"])

    def test_competition_prices_split_revenue(self):
        report = simulate(load_scenario(SIM / "scenarios" / "m2_competition.json"))
        medovy = next(row for row in report["days"][0]["demand"][0]["districts"] if row["id"] == "medovy_kvartal")
        by_id = {store["enterprise"]: store for store in medovy["stores"]}
        cheap = by_id["store_ref"]
        dear = by_id["store_dear"]
        self.assertEqual(cheap["price"], 90)
        self.assertEqual(dear["price"], 120)
        self.assertGreater(cheap["share"], dear["share"])
        self.assertEqual(cheap["sold"], cheap["share"])
        self.assertEqual(dear["sold"], dear["share"])
        self.assertEqual(cheap["revenue"], cheap["sold"] * 90)
        self.assertEqual(dear["revenue"], dear["sold"] * 120)
        self.assertGreater(report["totals"]["mira"]["revenue"], report["totals"]["oleg"]["revenue"])

    def test_modules_have_no_float_syntax(self):
        for name in ("districts.py", "demand.py", "formulas.py", "engine.py"):
            path = SIM / name
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                    self.fail(f"деление / в {name}")
                if isinstance(node, ast.Constant) and isinstance(node.value, float):
                    self.fail(f"дробный литерал в {name}")
                if isinstance(node, ast.Name) and node.id in {"float", "Decimal", "random"}:
                    self.fail(f"{node.id} в {name}")


if __name__ == "__main__":
    unittest.main()
