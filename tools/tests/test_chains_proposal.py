"""Предложение цепочек замкнуто и не трогает действующий каталог."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.validate_chains_proposal import load_proposal, validate

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "server" / "data"
CHANGED_RECIPES = (
    "dairy_milk",
    "slaughter_meat",
    "sawmill_wood",
    "cement_plant_cement",
    "steel_mill_steel",
    "textile_fabric",
    "electronics_plant_electronics",
)
CHANGED_BUILDINGS = ("grocery_store", "supermarket")
CHANGED_PRODUCTS = ("fuel",)


def _server(name):
    return json.loads((SERVER / f"{name}.json").read_text(encoding="utf-8"))


class ChainsProposalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_proposal()
        cls.errors = validate(cls.data)

    def test_proposal_is_closed(self):
        self.assertEqual(self.errors, [])

    def test_counts_and_no_product_exceptions(self):
        self.assertEqual(len(self.data["products"]), 41)
        self.assertEqual(len(self.data["buildings"]), 42)
        self.assertEqual(len(self.data["recipes"]), 41)
        self.assertEqual(self.data["sinks"]["product_exceptions"], [])

    def test_server_catalog_is_unchanged_snapshot(self):
        self.assertEqual(len(_server("products")), 25)
        self.assertEqual(len(_server("buildings")), 20)
        self.assertEqual(len(_server("recipes")), 17)
        recipes = {item["id"]: item for item in _server("recipes")}
        self.assertEqual(recipes["field_grain"]["outputs"]["grain"], 100)
        self.assertEqual(recipes["mill_flour"]["inputs"]["grain"], 100)
        self.assertEqual(recipes["mill_flour"]["outputs"]["flour"], 80)
        self.assertEqual(recipes["bakery_bread"]["outputs"]["bread"], 100)

    def test_existing_ids_kept_and_new_ids_are_new(self):
        for name in ("products", "buildings", "recipes"):
            old = {item["id"] for item in _server(name)}
            new = {item["id"] for item in self.data[name]}
            self.assertTrue(old <= new, name)
            self.assertEqual(len(new), len(self.data[name]))

    def test_only_marked_records_differ_from_server(self):
        for name, changed in (
            ("products", CHANGED_PRODUCTS),
            ("buildings", CHANGED_BUILDINGS),
            ("recipes", CHANGED_RECIPES),
        ):
            old = {item["id"]: item for item in _server(name)}
            new = {item["id"]: item for item in self.data[name]}
            for ident, before in old.items():
                if ident in changed:
                    self.assertNotEqual(before, new[ident], ident)
                    self.assertIn("Меняется", new[ident]["description"])
                else:
                    self.assertEqual(before, new[ident], ident)

    def test_m1_bread_path_quantities_stay(self):
        recipes = {item["id"]: item for item in self.data["recipes"]}
        self.assertEqual(recipes["field_grain"]["outputs"], {"grain": 100})
        self.assertEqual(recipes["mill_flour"]["inputs"], {"grain": 100})
        self.assertEqual(recipes["mill_flour"]["outputs"], {"flour": 80})
        self.assertEqual(recipes["bakery_bread"]["inputs"], {"flour": 80})
        self.assertEqual(recipes["bakery_bread"]["outputs"], {"bread": 100})
        self.assertEqual(recipes["refinery_fuel"]["outputs"]["fuel"], 300)

    def test_seven_consumer_chains_have_retail(self):
        goods = set()
        for building in self.data["buildings"]:
            if building["role"] == "retail":
                goods.update(building["allowed_goods"])
        for pid in (
            "bread", "kvass", "clothes", "furniture", "electronics",
            "appliances", "fuel", "car", "cement",
        ):
            self.assertIn(pid, {item["id"] for item in self.data["products"]})
        for pid in ("bread", "kvass", "clothes", "furniture", "electronics", "appliances", "fuel", "car"):
            self.assertIn(pid, goods)

    def test_hole_is_rejected(self):
        broken = json.loads(json.dumps(self.data))
        broken["recipes"] = [item for item in broken["recipes"] if item["id"] != "fishery_fish"]
        errors = validate(broken)
        self.assertTrue(any(line.startswith("fish: no source") for line in errors))
        self.assertTrue(any(line.startswith("smoked_fish: no source") for line in errors) or any("fish: no source" in line for line in errors))

    def test_cycle_is_rejected(self):
        broken = json.loads(json.dumps(self.data))
        broken["recipes"].append({
            "id": "loop_grain",
            "building": "feed_plant",
            "inputs": {"feed": 1},
            "outputs": {"grain": 1},
            "workers": 1,
            "technology_level": 1,
            "quality_model": "weighted_inputs_or_base",
            "balance": "draft",
            "name": "Петля",
            "description": "Тестовая петля.",
        })
        errors = validate(broken)
        self.assertTrue(any(line.startswith("cycle:") for line in errors), errors)

    def test_float_is_rejected(self):
        broken = json.loads(json.dumps(self.data))
        broken["products"][0]["reference_price"] = 1.5
        errors = validate(broken)
        self.assertTrue(any("float" in line for line in errors), errors)

    def test_consumer_without_shop_is_rejected(self):
        broken = json.loads(json.dumps(self.data))
        for building in broken["buildings"]:
            goods = building.get("allowed_goods")
            if goods and "car" in goods:
                building["allowed_goods"] = [pid for pid in goods if pid != "car"]
        errors = validate(broken)
        self.assertTrue(any(line.startswith("car: consumer good") for line in errors), errors)

    def test_sinks_are_integer_and_off_by_default(self):
        sinks = self.data["sinks"]
        self.assertEqual(sinks["construction"]["default"], 0)
        self.assertEqual(sinks["logistics"]["default"], 0)
        self.assertEqual(sinks["utility"]["default"], 0)
        self.assertEqual(sinks["construction"]["stages"]["commissioning"], {})
        self.assertGreater(sinks["construction"]["stages"]["foundation"]["cement"], 0)


if __name__ == "__main__":
    unittest.main()
