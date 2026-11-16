#!/usr/bin/env python3
"""Тесты валидатора данных ИИ-игроков."""
import json
import sys
import unittest
from pathlib import Path

# Добавляем путь к tools
sys.path.insert(0, str(Path(__file__).parent.parent))

import validate_ai_proposal as vap

class TestAIProposal(unittest.TestCase):
    def setUp(self):
        self.base = Path(vap.__file__).parent / "sim" / "data" / "ai_proposed"

    def test_files_exist_and_valid_json(self):
        for name in vap.REQUIRED_FILES:
            path = self.base / name
            self.assertTrue(path.exists(), f"нет {name}")
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertIsInstance(data, dict)

    def test_no_floats(self):
        for name in vap.REQUIRED_FILES:
            with open(self.base / name, encoding="utf-8") as f:
                data = json.load(f)
            vap.check_integers(data)  # raises on float

    def test_archetype_count_and_ids(self):
        with open(self.base / "archetypes.json", encoding="utf-8") as f:
            data = json.load(f)
        ids = [a["id"] for a in data["archetypes"]]
        self.assertGreaterEqual(len(ids), 8)
        self.assertEqual(len(ids), len(set(ids)))

    def test_persona_count_and_mark(self):
        with open(self.base / "personas.json", encoding="utf-8") as f:
            data = json.load(f)
        personas = data["personas"]
        self.assertGreaterEqual(len(personas), 12)
        self.assertLessEqual(len(personas), 16)
        for p in personas:
            self.assertEqual(p["ai_mark"], "Управляется ИИ")

    def test_templates_placeholders(self):
        with open(self.base / "reply_templates.json", encoding="utf-8") as f:
            data = json.load(f)
        self.assertGreaterEqual(len(data["templates"]), 30)
        for t in data["templates"]:
            for ph in t["placeholders"]:
                self.assertIn(ph, vap.ALLOWED_PLACEHOLDERS)

    def test_limits_integers(self):
        with open(self.base / "limits.json", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in data["limits"].items():
            self.assertIsInstance(v, int)
            self.assertGreaterEqual(v, 0)

    def test_validator_main_ok(self):
        # Запускаем как функцию
        old_exit = sys.exit
        try:
            sys.exit = lambda code=0: None if code == 0 else (_ for _ in ()).throw(SystemExit(code))
            result = vap.main()
            self.assertEqual(result, 0)
        finally:
            sys.exit = old_exit

if __name__ == "__main__":
    unittest.main()
