"""BE-106: versioned goods catalog. Legacy honey/oil/goods stay byte-for-byte the live market."""
import unittest

import economy
import game_server
import goods_catalog
import production


class CatalogInvariantTests(unittest.TestCase):
    def test_version_and_check(self):
        self.assertEqual(goods_catalog.CATALOG_VERSION, 1)
        self.assertTrue(goods_catalog.check())
        view = goods_catalog.public_view()
        self.assertEqual(view["version"], 1)
        self.assertEqual(view["retail_kind"], "shop")
        self.assertTrue(all(view["invariants"].values()))
        self.assertEqual({g["id"] for g in view["goods"]}, {g.id for g in goods_catalog.GOODS})

    def test_legacy_numbers_are_the_live_market(self):
        self.assertEqual(economy.PRODUCTION["farm"], {"product": "honey", "output": 100, "jobs": 4, "upkeep": 2000})
        self.assertEqual(economy.PRODUCTION["mine"], {"product": "oil", "output": 40, "jobs": 10, "upkeep": 15000})
        self.assertEqual(economy.PRODUCTION["factory"]["inputs"], {"oil": 10, "honey": 20})
        self.assertEqual(economy.PRODUCTION["factory"]["output"], 60)
        self.assertEqual(set(economy.MARKET), {"honey", "oil", "goods"})
        self.assertEqual(economy.MARKET["honey"]["reference_price"], 200)
        self.assertEqual(economy.MARKET["oil"]["reference_price"], 1500)
        self.assertEqual(economy.MARKET["goods"]["reference_price"], 2000)
        self.assertEqual(economy.MARKET["honey"]["base_demand"], 200)
        self.assertEqual(economy.MARKET["oil"]["base_demand"], 80)
        self.assertEqual(economy.MARKET["goods"]["base_demand"], 120)
        self.assertEqual(economy.MARKET["honey"]["season"], [1.15, 1.10, 1.00, 0.95, 0.90, 0.90, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15])
        self.assertEqual(economy.VAT_RATES["honey"], 0.10)
        self.assertEqual(economy.VAT_RATES["oil"], 0.22)
        self.assertEqual(economy.VAT_RATES["goods"], 0.22)
        self.assertLessEqual(max(economy.VAT_RATES.values()), 0.22)
        order = production.product_order()
        self.assertEqual(order[-1], "goods")
        self.assertEqual(set(order), {"honey", "oil", "goods"})

    def test_every_input_has_a_producer_and_there_is_no_cycle(self):
        order = goods_catalog.product_order()
        self.assertLess(order.index("grain"), order.index("flour"))
        self.assertLess(order.index("flour"), order.index("bread"))
        self.assertEqual(order[0], "honey")
        outputs = {item.output for item in goods_catalog.RECIPES if item.output}
        for item in goods_catalog.RECIPES:
            for raw in item.inputs:
                self.assertIn(raw, outputs)
        for item in goods_catalog.GOODS:
            self.assertGreater(item.base_demand, 0)
            self.assertIn(item.id, outputs)
            self.assertEqual(len(item.season), 12)

    def test_new_kinds_are_buildable_and_shop_specialization_ids_stay_free(self):
        for kind in ("grain_field", "elevator", "mill", "bread_plant", "oil_well", "gas_well", "sand_pit", "logging_camp"):
            self.assertIn(kind, game_server.KINDS)
            self.assertIn(kind, economy.BUILD_COST)
            self.assertEqual(game_server.KINDS[kind], (goods_catalog.recipe(kind).width, goods_catalog.recipe(kind).height))
        self.assertNotIn("bakery", game_server.KINDS)
        self.assertEqual(set(game_server.KINDS), set(economy.BUILD_COST))
        self.assertEqual(set(economy.terms()["building_costs"]),
                         {"farm", "mine", "factory", "warehouse", "shop", "school", "hospital", "park"})

    def test_reference_margin_is_finite_and_the_price_floor_loses_money(self):
        """A first building at the reference price earns less than it cost to build.
        At MIN_PRICE_K the same building loses money even before taxes, so scaling cannot print cash.
        """
        for item in goods_catalog.RECIPES:
            if not item.output or item.legacy:
                continue
            ref = goods_catalog.good(item.output).reference_price
            floor = int(round(ref * economy.MIN_PRICE_K))
            self.assertEqual(economy.price_for(item.output, 10 ** 9, 1), floor)
            wages = item.jobs * economy.BASE_WAGE
            overhead = wages + item.upkeep

            def margin(price, raw_k):
                revenue = item.capacity * price
                inputs = 0
                for raw, qty in item.inputs.items():
                    raw_price = int(round(goods_catalog.good(raw).reference_price * raw_k))
                    inputs += qty * raw_price
                return revenue - inputs - overhead

            at_ref = margin(ref, 1.0)
            at_floor = margin(floor, economy.MIN_PRICE_K)
            self.assertGreater(at_ref, 0, item.kind)
            self.assertLess(at_ref, item.build_cost, item.kind)
            self.assertLess(at_floor, 0, item.kind)

    def test_consumer_goods_have_the_shop_as_buyer(self):
        consumers = [g.id for g in goods_catalog.GOODS if g.consumer]
        self.assertEqual(consumers, ["honey", "goods", "bread"])
        self.assertEqual(economy.PRODUCTION["shop"]["role"], "retail")
        self.assertEqual(economy.VAT_RATES["bread"], 0.10)
        self.assertEqual(economy.VAT_RATES["grain"], 0.10)
        self.assertEqual(economy.VAT_RATES["flour"], 0.10)
        self.assertEqual(economy.VAT_RATES["gas"], 0.22)
        self.assertEqual(economy.VAT_RATES["sand"], 0.22)
        self.assertEqual(economy.VAT_RATES["timber"], 0.22)


if __name__ == "__main__":
    unittest.main()
