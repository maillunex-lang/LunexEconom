"""Mutation and arithmetic tests for the draft real-estate proposal."""
import copy
import unittest

from tools.validate_realestate_proposal import ValidationError, has_cycles, load_data, validate


class RealestateProposalTests(unittest.TestCase):
    def setUp(self):
        self.data = load_data()

    def mutate(self, filename, field, value):
        updated = copy.deepcopy(self.data)
        updated[filename][field] = value
        return updated

    def test_valid_fixture(self):
        self.assertEqual(validate(self.data), {"buildings": 6, "leases": 4, "mall_returns": 3, "transitions": 16})

    def test_no_floats_anywhere(self):
        from tools.validate_realestate_proposal import check_types
        with self.assertRaises(ValidationError):
            check_types({"rate": 0.5})
        with self.assertRaises(ValidationError):
            check_types({"rate": 2**63})

    def test_bool_is_not_integer(self):
        updated = copy.deepcopy(self.data)
        updated["limits.json"]["max_area_per_player_per_city_m2"] = True
        with self.assertRaises(ValidationError):
            validate(updated)

    def test_overbooked_property(self):
        updated = copy.deepcopy(self.data)
        lease = updated["lease_examples.json"]["leases"][0]
        lease["area_m2"] = 1200
        with self.assertRaises(ValidationError):
            validate(updated)

    def test_duplicate_unit(self):
        updated = copy.deepcopy(self.data)
        updated["lease_examples.json"]["leases"][1]["unit_id"] = "prop-1-u1"
        with self.assertRaisesRegex(ValidationError, "double-leased"):
            validate(updated)

    def test_player_building_cap(self):
        updated = copy.deepcopy(self.data)
        updated["lease_examples.json"]["leases"][1]["tenant"] = "hold-b"
        updated["limits.json"]["max_area_share_per_building_permille"] = 200
        with self.assertRaises(ValidationError):
            validate(updated)

    def test_player_city_cap(self):
        updated = copy.deepcopy(self.data)
        updated["limits.json"]["max_area_per_player_per_city_m2"] = 150
        with self.assertRaises(ValidationError):
            validate(updated)

    def test_out_of_range_rent(self):
        updated = copy.deepcopy(self.data)
        updated["lease_examples.json"]["leases"][0]["rate_rub_per_m2_month"] = 151
        with self.assertRaises(ValidationError):
            validate(updated)

    def test_deposit_must_match(self):
        updated = copy.deepcopy(self.data)
        updated["lease_examples.json"]["leases"][0]["deposit_rub"] = 0
        with self.assertRaises(ValidationError):
            validate(updated)

    def test_invalid_term(self):
        updated = copy.deepcopy(self.data)
        updated["lease_examples.json"]["leases"][1]["term_months"] = 1
        with self.assertRaises(ValidationError):
            validate(updated)

    def test_negative_area(self):
        updated = copy.deepcopy(self.data)
        updated["lease_examples.json"]["leases"][0]["area_m2"] = -100
        with self.assertRaises(ValidationError):
            validate(updated)

    def test_lifecycle_cycle(self):
        updated = copy.deepcopy(self.data)
        updated["lifecycle.json"]["transitions"]["delinquent"].append("active")
        self.assertTrue(has_cycles(updated["lifecycle.json"]["transitions"]))
        with self.assertRaisesRegex(ValidationError, "cycles"):
            validate(updated)

    def test_lifecycle_unknown_state(self):
        updated = copy.deepcopy(self.data)
        updated["lifecycle.json"]["transitions"]["draft"].append("unknown")
        with self.assertRaises(ValidationError):
            validate(updated)

    def test_mall_net_recomputed(self):
        updated = copy.deepcopy(self.data)
        updated["mall_returns.json"]["cases"][0]["net_month_rub"] += 1
        with self.assertRaisesRegex(ValidationError, "net_month_rub"):
            validate(updated)

    def test_mall_payback_recomputed(self):
        updated = copy.deepcopy(self.data)
        updated["mall_returns.json"]["cases"][1]["payback_months"] += 1
        with self.assertRaisesRegex(ValidationError, "payback_months"):
            validate(updated)

    def test_modularity(self):
        updated = copy.deepcopy(self.data)
        updated["lease_examples.json"]["leases"][0]["area_m2"] = 201
        with self.assertRaises(ValidationError):
            validate(updated)

    def test_occupancy_capacity_and_retail_cells(self):
        limits = self.data["limits.json"]
        self.assertEqual(100 // limits["retail_m2_per_cell"], 5)
        self.assertEqual((100 * limits["retail_stock_area_permille"] // 1000) * limits["retail_stock_units_per_m2"], 500)


    def test_traffic_factor_math_exact(self):
        baseline = 70 * 1000 * 1000 * 1000 * 1000 * 1000 // 1000000000000000
        boosted = 70 * 1000 * 1200 * 1000 * 900 * 1000 // 1000000000000000
        self.assertEqual(baseline, 70)
        self.assertEqual(boosted, 75)

    def test_realestate_land_tax_math(self):
        self.assertEqual(15000 * 10000 * 16000 // 100000000, 24000)
        self.assertEqual((480000 + 24000) * 20 // 10000, 1008)
        self.assertEqual((504000 + 11722 - 1) // 11722, 43)


if __name__ == "__main__":
    unittest.main()
