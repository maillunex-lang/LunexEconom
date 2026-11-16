"""Предложение монетизации целое, без запрещённых привилегий и без правок сервера."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.validate_monetization import (
    auto_cap,
    executive_salary,
    load_proposal,
    shelf_price,
    validate,
)

ROOT = Path(__file__).resolve().parents[2]


class MonetizationProposalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_proposal()
        cls.errors = validate(cls.data)

    def test_proposal_is_closed(self):
        self.assertEqual(self.errors, [])

    def test_counts_and_recommendation(self):
        plans = self.data["plans"]["plans"]
        self.assertEqual(len(plans), 9)
        self.assertEqual(sum(plan["sellable"] for plan in plans), 3)
        self.assertEqual(self.data["plans"]["recommended_variant"], "A")
        self.assertEqual(self.data["automation"]["flags"]["accel_enabled"], 0)
        self.assertEqual(len(self.data["packages"]["packages"]), 4)
        self.assertEqual(len(self.data["cosmetics"]["cosmetics"]), 15)
        self.assertGreaterEqual(len(self.data["shop_lines"]["lines"]), 12)
        banned = {row["id"] for row in self.data["forbidden"]["forbidden"]}
        for ban in ("grant_game_rubles", "lootbox_random", "market_advantage_exclusive", "hidden_autorenew"):
            self.assertIn(ban, banned)

    def test_sellable_plans_have_no_forbidden_or_accel(self):
        forbidden = {row["id"] for row in self.data["forbidden"]["forbidden"]}
        for plan in self.data["plans"]["plans"]:
            self.assertEqual(plan["auto_renew_default"], 0)
            self.assertTrue(plan["description"])
            self.assertTrue(plan["cancel_text"])
            self.assertTrue(forbidden.isdisjoint(plan["privileges"]))
            if plan["sellable"] == 1:
                self.assertNotIn("construction_accel_token", plan["privileges"])
                self.assertNotIn("grant_game_rubles", plan["privileges"])

    def test_packages_are_cosmetic_only(self):
        for pack in self.data["packages"]["packages"]:
            self.assertGreater(pack["price_rub"], 0)
            self.assertNotIn("automation_slots_bonus", pack["privileges"])
            self.assertNotIn("construction_accel_token", pack["privileges"])

    def test_integer_examples(self):
        self.assertEqual(shelf_price(100, 1, 500, 97, 0), 97)
        self.assertEqual(shelf_price(100, 1, 500, 50, 0), 95)
        self.assertEqual(shelf_price(100, 0, 500, 1, 0), 100)
        self.assertEqual(shelf_price(100, 2, 2000, 1, 0), 120)
        self.assertEqual(executive_salary(2000, 7, 1000), 14000)
        self.assertEqual(executive_salary(2000, 5, 1000), 10000)
        self.assertEqual(auto_cap(2, 4, 0, 4), 6)
        self.assertEqual(auto_cap(2, 4, 1, 4), 6)
        self.assertEqual(auto_cap(2, 0, 1, 4), 6)
        self.assertEqual(auto_cap(2, 24, 6, 4), 26)
        self.assertEqual(auto_cap(2, 24, 0, 4), 26)

    def test_server_and_client_are_not_this_proposal(self):
        self.assertFalse((ROOT / "server" / "monetization").exists())
        self.assertFalse((ROOT / "client" / "monetization").exists())

    def test_duplicate_plan_id_is_rejected(self):
        broken = json.loads(json.dumps(self.data))
        broken["plans"]["plans"][1]["id"] = broken["plans"]["plans"][0]["id"]
        errors = validate(broken)
        self.assertTrue(any("duplicate plan id" in line for line in errors), errors)

    def test_float_is_rejected(self):
        broken = json.loads(json.dumps(self.data))
        broken["plans"]["plans"][0]["price_rub"] = 1.5
        errors = validate(broken)
        self.assertTrue(any("float" in line for line in errors), errors)

    def test_bool_is_rejected(self):
        broken = json.loads(json.dumps(self.data))
        broken["automation"]["flags"]["accel_enabled"] = True
        errors = validate(broken)
        self.assertTrue(any("bool" in line for line in errors), errors)

    def test_forbidden_privilege_is_rejected(self):
        broken = json.loads(json.dumps(self.data))
        plan = broken["plans"]["plans"][0]
        plan["privileges"].append("grant_game_rubles")
        plan["grants"].append({"privilege": "grant_game_rubles", "amount": 1})
        errors = validate(broken)
        self.assertTrue(any("forbidden privilege grant_game_rubles" in line for line in errors), errors)

    def test_unknown_privilege_is_rejected(self):
        broken = json.loads(json.dumps(self.data))
        plan = broken["plans"]["plans"][0]
        plan["privileges"].append("sparkles")
        plan["grants"].append({"privilege": "sparkles", "amount": 1})
        errors = validate(broken)
        self.assertTrue(any("unknown privilege sparkles" in line for line in errors), errors)

    def test_missing_description_and_cancel_are_rejected(self):
        broken = json.loads(json.dumps(self.data))
        broken["plans"]["plans"][0]["description"] = " "
        broken["plans"]["plans"][1]["cancel_text"] = ""
        errors = validate(broken)
        self.assertTrue(any(line.endswith("missing description") for line in errors), errors)
        self.assertTrue(any(line.endswith("missing cancel text") for line in errors), errors)

    def test_non_positive_limit_is_rejected(self):
        broken = json.loads(json.dumps(self.data))
        broken["automation"]["limits"]["free_auto_slots"] = 0
        errors = validate(broken)
        self.assertTrue(any("free_auto_slots" in line for line in errors), errors)

    def test_negative_price_is_rejected(self):
        broken = json.loads(json.dumps(self.data))
        broken["packages"]["packages"][0]["price_rub"] = -1
        errors = validate(broken)
        self.assertTrue(any("cannot be negative" in line for line in errors), errors)

    def test_variant_c_cannot_be_sold(self):
        broken = json.loads(json.dumps(self.data))
        for plan in broken["plans"]["plans"]:
            if plan["variant"] == "C":
                plan["sellable"] = 1
        errors = validate(broken)
        self.assertTrue(any("variant C must not be sellable" in line for line in errors), errors)

    def test_pressure_copy_is_rejected(self):
        broken = json.loads(json.dumps(self.data))
        broken["plans"]["plans"][0]["description"] += " успей"
        errors = validate(broken)
        self.assertTrue(any(line.startswith("pressure:") for line in errors), errors)

    def test_slot_bonus_must_match_executives(self):
        broken = json.loads(json.dumps(self.data))
        grant = broken["plans"]["plans"][0]["grants"][0]
        self.assertEqual(grant["privilege"], "automation_slots_bonus")
        grant["amount"] = 5
        errors = validate(broken)
        self.assertTrue(any("whole executives" in line for line in errors), errors)

    def test_package_cannot_sell_automation(self):
        broken = json.loads(json.dumps(self.data))
        broken["packages"]["packages"][0]["privileges"].append("automation_slots_bonus")
        errors = validate(broken)
        self.assertTrue(any("not cosmetic" in line for line in errors), errors)

    def test_float_token_in_file_is_rejected(self):
        import tempfile
        from tools.validate_monetization import FILES, PROPOSAL, ProposalError

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for name in FILES:
                (folder / f"{name}.json").write_text(
                    (PROPOSAL / f"{name}.json").read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            broken = (folder / "plans.json").read_text(encoding="utf-8").replace(
                '"price_rub": 149', '"price_rub": 149.5', 1
            )
            (folder / "plans.json").write_text(broken, encoding="utf-8")
            with self.assertRaises(ProposalError):
                load_proposal(folder)


if __name__ == "__main__":
    unittest.main()
