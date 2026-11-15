"""Прогоны M1 против эталона и честный вердикт приёмки."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.sim.catalog import Catalog, salary_worker_draft
from tools.sim.engine import load_scenario, simulate
from tools.sim.formulas import clearing_price, monthly_expense, vat_on_gross


ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT / "tools" / "sim"


def run(name: str):
    return simulate(load_scenario(SIM / "scenarios" / f"{name}.json"))


class GoldenTests(unittest.TestCase):
    def test_golden_files_match_runs(self):
        for path in sorted((SIM / "scenarios").glob("*.json")):
            golden_path = SIM / "golden" / f"{path.stem}.json"
            self.assertTrue(golden_path.is_file(), golden_path)
            expected = json.loads(golden_path.read_text(encoding="utf-8"))
            actual = simulate(load_scenario(path))
            self.assertEqual(actual, expected)

    def test_every_day_keeps_a_balanced_ledger_and_solvent_players(self):
        for path in sorted((SIM / "scenarios").glob("*.json")):
            report = simulate(load_scenario(path))
            for row in report["days"]:
                self.assertEqual(row["ledger_sum"], 0)
                for player in row["players"].values():
                    self.assertGreaterEqual(player["money"], 0)
            for total in report["totals"].values():
                self.assertGreaterEqual(total["min_money"], 0)


class UnderfundedTests(unittest.TestCase):
    def test_arrears_stop_production_until_cash_arrives(self):
        catalog = Catalog()
        report = run("m1_underfunded")
        building = catalog.building("field")
        expense = monthly_expense(
            int(building["jobs"]),
            int(building["upkeep_month"]),
            salary_worker_draft(),
            10000,
            int(catalog.city("ufa")["indices_bp"]["salary"]),
        )
        by_day = {row["day"]: row for row in report["days"]}
        self.assertGreater(expense, 0)
        self.assertEqual(by_day[1]["players"]["anna"]["money"], 0)
        self.assertEqual(by_day[30]["enterprises"]["field"]["arrears"], expense)
        self.assertEqual(by_day[30]["players"]["anna"]["output"].get("grain", 0), int(catalog.recipe_for("field_grain")["outputs"]["grain"]))
        self.assertEqual(by_day[31]["players"]["anna"]["output"], {})
        self.assertEqual(by_day[31]["enterprises"]["field"]["load_bp"], 0)
        self.assertEqual(by_day[60]["enterprises"]["field"]["arrears"], expense * 2)
        self.assertEqual(by_day[69]["enterprises"]["field"]["load_bp"], 0)
        self.assertEqual(by_day[70]["enterprises"]["field"]["arrears"], 0)
        self.assertEqual(by_day[70]["enterprises"]["field"]["load_bp"], 10000)
        self.assertEqual(by_day[70]["players"]["anna"]["money"], 20000 - expense * 2)
        self.assertEqual(by_day[71]["enterprises"]["field"]["load_bp"], 10000)
        # Склад поля черновой и заполняется. Это уже не просрочка: долг погашен.
        capacity = int(building["storage_capacity"])
        self.assertEqual(by_day[81]["enterprises"]["field"]["stock"]["grain"], capacity)
        self.assertEqual(by_day[81]["enterprises"]["field"]["load_bp"], 0)
        self.assertEqual(by_day[81]["enterprises"]["field"]["arrears"], 0)
        self.assertEqual(report["totals"]["anna"]["min_money"], 0)


class BasicAcceptanceTests(unittest.TestCase):
    def test_m1_acceptance_is_reached_on_starter_chain_costs(self):
        # Владелец утвердил черновую стоимость стартового набора (поле 39000, мельница 65000, пекарня 78000,
        # магазин 52000, итого 234000 при капитале 1000000 в сценарии). Раньше при 1600000 приёмка M1 не достигалась.
        catalog = Catalog()
        report = run("m1_basic")
        verdict = report["verdict"]
        self.assertIsNotNone(verdict)
        self.assertTrue(verdict["accepted"])
        self.assertTrue(verdict["chain_operational"])
        self.assertGreater(verdict["revenue_first_window"], 0)
        self.assertLessEqual(verdict["build_cost_sum"], verdict["starting_capital"])
        self.assertGreater(report["totals"]["mira"]["revenue"], 0)
        self.assertGreater(report["totals"]["mira"]["output"]["flour"], 0)
        # Мука не потребительский товар: выручка идёт только от хлеба в магазине.
        self.assertFalse(catalog.product("flour")["consumer"])
        self.assertTrue(catalog.product("bread")["consumer"])

    def test_city_flour_at_corridor_ceiling_loses_money(self):
        catalog = Catalog()
        recipe = catalog.recipe_for("bakery_bread")
        flour_in = int(recipe["inputs"]["flour"])
        bread_out = int(recipe["outputs"]["bread"])
        flour_ref = int(catalog.product("flour")["reference_price"])
        bread_ref = int(catalog.product("bread")["reference_price"])
        ceiling = clearing_price(flour_ref, 1, 0)
        self.assertEqual(ceiling, flour_ref * 250 // 100)
        daily_revenue = bread_out * bread_ref
        daily_cost = flour_in * ceiling
        daily_vat = vat_on_gross(daily_revenue)
        self.assertGreater(daily_cost + daily_vat, daily_revenue)
        reference_cost = flour_in * flour_ref
        self.assertGreater(daily_revenue, reference_cost + daily_vat)


class TwoPlayerTests(unittest.TestCase):
    def test_shared_market_pays_both_players(self):
        catalog = Catalog()
        report = run("m1_two_players")
        bread = int(catalog.recipe_for("bakery_bread")["outputs"]["bread"])
        price = int(catalog.product("bread")["reference_price"])
        steady = report["days"][2]
        self.assertEqual(steady["players"]["timur"]["sales"], bread)
        self.assertEqual(steady["players"]["timur"]["revenue"], bread * price)
        self.assertEqual(steady["market"][0]["product"], "flour")
        self.assertEqual(steady["market"][0]["price"], int(catalog.product("flour")["reference_price"]))
        self.assertGreater(report["totals"]["timur"]["revenue"], 0)
        self.assertGreater(report["totals"]["timur"]["money"], 200000)
        self.assertGreater(report["totals"]["mira"]["money"], 200000)
        self.assertGreater(report["totals"]["mira"]["min_money"], 0)
        self.assertGreater(report["totals"]["timur"]["min_money"], 0)


if __name__ == "__main__":
    unittest.main()
