"""Catalog must not silently make unbalanced/unpriced specializations buildable."""
import unittest
import construction_catalog
import economy
import game_server


class ConstructionCatalogTests(unittest.TestCase):
    def test_trade_catalog_has_33_unique_specializations(self):
        items = construction_catalog.view()["trade_specializations"]
        self.assertEqual(len(items), 33)
        self.assertEqual(len({item["id"] for item in items}), 33)
        self.assertEqual(sum(item["role"] == "wholesale" for item in items), 4)
        self.assertTrue(all(item["base_kind"] == "shop" for item in items))

    def test_existing_building_prices_unchanged(self):
        entries = construction_catalog.view()["base_buildings"]
        self.assertEqual({x["kind"]: x["build_cost"] for x in entries}, economy.BUILD_COST)
        self.assertEqual(set(game_server.KINDS), set(economy.BUILD_COST))

    def test_new_specializations_are_not_buildable_yet(self):
        items = construction_catalog.view()["trade_specializations"]
        self.assertTrue(all(not item["enabled"] for item in items))
        for item in items:
            self.assertNotIn(item["id"], game_server.KINDS)


if __name__ == "__main__":
    unittest.main()
