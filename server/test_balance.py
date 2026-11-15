"""EX-02: one registry, same defaults, env and file overrides."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

import balance
import economy


class BalanceRegistryTests(unittest.TestCase):
    def test_defaults_match_the_live_economy_constants(self):
        self.assertEqual(economy.BASE_WAGE, balance.DEFAULTS["BASE_WAGE"])
        self.assertEqual(economy.START_CAPITAL, balance.DEFAULTS["START_CAPITAL"])
        self.assertEqual(economy.DEFAULT_PROFIT_TAX, balance.DEFAULTS["DEFAULT_PROFIT_TAX"])
        self.assertEqual(economy.DEFAULT_PROPERTY_TAX, balance.DEFAULTS["DEFAULT_PROPERTY_TAX"])
        self.assertEqual(economy.LOAN_INTEREST, balance.DEFAULTS["LOAN_INTEREST"])
        self.assertEqual(economy.MIGRATION_IN, balance.DEFAULTS["MIGRATION_IN"])
        self.assertEqual(economy.RETAIL_MARKUP, balance.DEFAULTS["RETAIL_MARKUP"])
        self.assertEqual(economy.OWNER_SPEND_SHARE, balance.DEFAULTS["OWNER_SPEND_SHARE"])
        self.assertEqual(economy.ROAD_CELL_COST, balance.DEFAULTS["ROAD_CELL_COST"])
        self.assertEqual(economy.BUILD_COST["shop"], balance.DEFAULTS["SHOP_COST"])
        self.assertEqual(economy.BUILD_COST["warehouse"], balance.DEFAULTS["WAREHOUSE_COST"])
        self.assertEqual(economy.MIN_PRICE_K, 0.25)
        self.assertEqual(economy.MAX_PRICE_K, 2.5)
        self.assertEqual(balance.get("NPC_NEW_KINDS"), 0)
        self.assertEqual(balance.get("TRUCK_CAPACITY"), 40)
        view = balance.public_view()
        self.assertIn("zones", view)
        self.assertIn("transport", view)
        self.assertEqual(view["zones"]["ZONE_CORE_SHARE"], 0.40)

    def test_environment_override_is_what_a_fresh_import_reads(self):
        env = os.environ.copy()
        env["LUNEX_BAL_BASE_WAGE"] = "1600"
        env.pop("LUNEX_BALANCE_FILE", None)
        out = subprocess.check_output(
            [sys.executable, "-c", "import economy; print(economy.BASE_WAGE)"],
            cwd=os.path.dirname(__file__), env=env, text=True)
        self.assertEqual(out.strip(), "1600")
        self.assertEqual(economy.BASE_WAGE, 1500)

    def test_file_override_and_unknown_keys(self):
        previous = os.environ.get("LUNEX_BALANCE_FILE")
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
                json.dump({"TRUCK_PRICE": 1000, "not_a_parameter": 5}, handle)
                path = handle.name
            os.environ["LUNEX_BALANCE_FILE"] = path
            os.environ.pop("LUNEX_BAL_TRUCK_PRICE", None)
            balance.reload()
            self.assertEqual(balance.get("TRUCK_PRICE"), 1000)
            self.assertEqual(balance.get("BASE_WAGE"), balance.DEFAULTS["BASE_WAGE"])
        finally:
            if previous is None:
                os.environ.pop("LUNEX_BALANCE_FILE", None)
            else:
                os.environ["LUNEX_BALANCE_FILE"] = previous
            balance.reload()
            self.assertEqual(balance.get("TRUCK_PRICE"), balance.DEFAULTS["TRUCK_PRICE"])


if __name__ == "__main__":
    unittest.main()
