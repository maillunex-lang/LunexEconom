import unittest
import industry_catalog as ic

class IndustryCatalogTests(unittest.TestCase):
    def test_every_chain_has_supplier_and_no_cycles(self):
        self.assertEqual(len(ic.order()), len(ic.RECIPES))
        self.assertLess(ic.order().index("iron_mine"), ic.order().index("steelworks"))
        self.assertLess(ic.order().index("steelworks"), ic.order().index("machine_plant"))
        self.assertLess(ic.order().index("grain_farm"), ic.order().index("flour_mill"))
        self.assertLess(ic.order().index("flour_mill"), ic.order().index("bakery"))

    def test_upgrades_increase_output_and_cost(self):
        base = ic.quote("steelworks")
        expanded = ic.quote("steelworks", 2, 2)
        self.assertGreater(expanded["output"], base["output"])
        self.assertGreater(expanded["upkeep"], base["upkeep"])
        self.assertGreater(expanded["inputs"]["iron_ore"], base["inputs"]["iron_ore"])

    def test_no_inputs_no_factory_output(self):
        self.assertEqual(ic.max_output("steelworks", {}), 0)
        self.assertEqual(ic.max_output("steelworks", {"iron_ore": 60, "coal": 30}), 50)
        self.assertEqual(ic.max_output("steelworks", {"iron_ore": 30, "coal": 30}), 25)

    def test_strict_input_validation(self):
        for args in [("steelworks", True, 1), ("steelworks", 1, 4), ("missing", 1, 1)]:
            with self.assertRaises(ValueError):
                ic.quote(*args)
        with self.assertRaises(ValueError):
            ic.max_output("steelworks", {"iron_ore": -1})

    def test_expansion_and_upgrade_rules(self):
        self.assertGreater(ic.expansion_cost("steelworks", 1, 2), 0)
        self.assertGreater(ic.upgrade_cost("steelworks", 1, 2), 0)
        with self.assertRaises(ValueError):
            ic.expansion_cost("steelworks", 2, 2)
        with self.assertRaises(ValueError):
            ic.upgrade_cost("steelworks", 1, 3)

if __name__ == "__main__":
    unittest.main()