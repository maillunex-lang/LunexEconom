"""Предложенные манифесты контента: схема, лимиты, циклы, хост."""
from __future__ import annotations

import json
import unittest

from tools.validate_content_manifest import (
    check_tree,
    load_limits,
    load_manifest,
    validate_manifest,
)


class ContentManifestTests(unittest.TestCase):
    def test_examples_match_the_policy(self):
        problems, good, bad = check_tree()
        self.assertEqual(problems, [])
        self.assertEqual(good, ["icons_goods.json", "ui_theme.json", "season_winter.json"])
        self.assertEqual(len(bad), 1)
        self.assertTrue(any("cycle:" in item for item in bad[0][1]))
        self.assertTrue(any("url must stay" in item for item in bad[0][1]))

    def test_limits_are_integers_under_the_client_ceiling(self):
        limits = load_limits()
        self.assertLessEqual(limits["max_release_bytes"], limits["cache_bytes"])
        self.assertLessEqual(limits["cellular_budget_bytes"], limits["max_release_bytes"])
        for size in limits["pack_bytes"].values():
            self.assertIs(type(size), int)
            self.assertLessEqual(size, limits["client_pack_ceiling_bytes"])

    def test_float_size_is_rejected(self):
        limits = load_limits()
        data, _raw = load_manifest(_icons())
        data["packs"][0]["size"] = 1.5
        errors = validate_manifest(data, limits)
        self.assertTrue(any("float" in item or "schema" in item for item in errors), errors)

    def test_kind_limit_is_enforced(self):
        limits = load_limits()
        data, _raw = load_manifest(_icons())
        data["packs"][0]["size"] = limits["pack_bytes"]["icons_goods"] + 1
        errors = validate_manifest(data, limits)
        self.assertTrue(any("kind limit" in item for item in errors), errors)

    def test_min_version_code_stays_positive(self):
        limits = load_limits()
        data, _raw = load_manifest(_icons())
        data["packs"][0]["min_version_code"] = 0
        errors = validate_manifest(data, limits)
        self.assertTrue(errors)

    def test_release_version_must_match_pack_version(self):
        limits = load_limits()
        data, _raw = load_manifest(_icons())
        data["release"] = 4
        errors = validate_manifest(data, limits)
        self.assertTrue(any("version must equal release" in item for item in errors), errors)


def _icons():
    from pathlib import Path
    return Path(__file__).resolve().parents[1] / "sim" / "data" / "content_proposed" / "icons_goods.json"


if __name__ == "__main__":
    unittest.main()
