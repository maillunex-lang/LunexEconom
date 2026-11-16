#!/usr/bin/env python3
"""Тесты предложения «Карта 3D»: схема, порядок, повтор, догонка, бюджеты."""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import validate_map3d_proposal as proposal


class TestMap3DProposal(unittest.TestCase):
    def setUp(self):
        self.base = Path(proposal.__file__).parent / "sim" / "data" / "map3d_proposed"

    def test_files_exist_and_json(self):
        for name in proposal.REQUIRED:
            path = self.base / name
            self.assertTrue(path.exists(), name)
            with path.open(encoding="utf-8") as handle:
                self.assertIsInstance(json.load(handle), dict)

    def test_no_floats(self):
        for name in proposal.REQUIRED:
            with (self.base / name).open(encoding="utf-8") as handle:
                proposal.check_numbers(json.load(handle), name)

    def test_examples_match_schema_and_size(self):
        schema = json.loads((self.base / "event.schema.json").read_text(encoding="utf-8"))
        examples = json.loads((self.base / "examples.json").read_text(encoding="utf-8"))
        limits = json.loads((self.base / "limits.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(examples["events"]), 6)
        self.assertLessEqual(len(examples["events"]), 8)
        errors = []
        previous = 0
        for event in examples["events"]:
            proposal.validate_schema(schema, schema, event, "event", errors)
            self.assertGreater(event["event_id"], previous)
            self.assertEqual(event["event_id"], event["version"])
            previous = event["event_id"]
            self.assertLessEqual(len(proposal.compact_bytes(event)), limits["max_event_bytes"])
        self.assertEqual(errors, [])

    def test_remove_missing_is_rejected(self):
        examples = json.loads((self.base / "examples.json").read_text(encoding="utf-8"))
        by_id = {event["event_id"]: event for event in examples["events"]}
        missing = next(item for item in examples["sequences"] if item["id"] == "remove_missing_building")
        self.assertEqual(
            proposal.apply_sequence([by_id[step] for step in missing["steps"]]),
            "missing_object",
        )

    def test_replay_is_idempotent_and_order_is_kept(self):
        examples = json.loads((self.base / "examples.json").read_text(encoding="utf-8"))
        by_id = {event["event_id"]: event for event in examples["events"]}
        replay = next(item for item in examples["sequences"] if item["id"] == "replay_same_event")
        backwards = next(item for item in examples["sequences"] if item["id"] == "out_of_order")
        self.assertEqual(proposal.apply_sequence([by_id[step] for step in replay["steps"]]), "apply")
        self.assertEqual(proposal.apply_sequence([by_id[step] for step in backwards["steps"]]), "out_of_order")

    def test_catchup_gap_and_snapshot(self):
        examples = json.loads((self.base / "examples.json").read_text(encoding="utf-8"))
        limits = json.loads((self.base / "limits.json").read_text(encoding="utf-8"))
        found = {item["id"]: item for item in examples["catchup"]}
        self.assertEqual(proposal.plan_catchup(found["unexplained_hole"], limits["catchup_max_gap"]), "catchup")
        self.assertEqual(proposal.plan_catchup(found["too_far"], limits["catchup_max_gap"]), "snapshot")
        self.assertEqual(proposal.plan_catchup(found["replay_only"], limits["catchup_max_gap"]), "ignore")

    def test_budgets_positive_and_formula(self):
        budgets = json.loads((self.base / "budgets.json").read_text(encoding="utf-8"))
        errors = []
        proposal.positive_integers(
            {key: value for key, value in budgets.items() if key != "balance"},
            "budgets",
            errors,
        )
        proposal.check_budgets(budgets, errors)
        self.assertEqual(errors, [])
        self.assertEqual(budgets["balance"], "draft")

    def test_float_injection_is_rejected(self):
        examples = json.loads((self.base / "examples.json").read_text(encoding="utf-8"))
        broken = copy.deepcopy(examples)
        broken["events"][0]["object"]["color_rgb"] = 1.5
        with self.assertRaises(SystemExit):
            proposal.check_numbers(broken, "broken")

    def test_validator_main_ok(self):
        self.assertEqual(proposal.main(), 0)


if __name__ == "__main__":
    unittest.main()
