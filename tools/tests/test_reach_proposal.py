"""Draft reach proposal datasets and reproduction checks."""
from __future__ import annotations

import copy
import unittest

from tools.validate_reach_proposal import ValidationError, check_types, integer, validate


class ReachProposalTests(unittest.TestCase):
    def test_datasets_and_goldens(self):
        self.assertEqual(validate()["validated_scenarios"], 6)

    def test_float_bool_and_overflow_rejected(self):
        with self.assertRaises(ValidationError):
            check_types({"invalid": 0.25})
        with self.assertRaises(ValidationError):
            integer(True, "bool", 0, 1000)
        with self.assertRaises(ValidationError):
            integer(1001, "permille", 0, 1000)
        with self.assertRaises(ValidationError):
            check_types({"overflow": 2**63})
