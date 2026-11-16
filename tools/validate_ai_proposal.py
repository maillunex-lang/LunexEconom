#!/usr/bin/env python3
"""Валидатор предложения данных ИИ-игроков. Только целые числа, без секретов."""
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).parent / "sim" / "data" / "ai_proposed"

REQUIRED_FILES = ["archetypes.json", "personas.json", "reply_templates.json", "limits.json"]
ALLOWED_PLACEHOLDERS = {"{company}", "{city}", "{goods}", "{price_rub}", "{days}"}
FORBIDDEN_PHRASES = [
    "я человек", "я живой", "реальные деньги", "переведи на карту",
    "email", "пароль", "токен", "выход из игры", "личные данные"
]

def load_json(name):
    path = BASE / name
    if not path.exists():
        raise SystemExit(f"FAIL: файл {name} отсутствует")
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def check_integers(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            check_integers(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            check_integers(v, f"{path}[{i}]")
    elif isinstance(obj, float):
        raise SystemExit(f"FAIL: float запрещён в {path}")
    elif isinstance(obj, (int, str, bool, type(None))):
        pass
    else:
        raise SystemExit(f"FAIL: неожиданный тип в {path}")

def main():
    errors = []
    data = {}
    for name in REQUIRED_FILES:
        try:
            data[name] = load_json(name)
            check_integers(data[name])
        except SystemExit as e:
            errors.append(str(e))
            continue

    if "archetypes.json" in data:
        arch_ids = [a["id"] for a in data["archetypes.json"]["archetypes"]]
        if len(arch_ids) != len(set(arch_ids)):
            errors.append("FAIL: id архетипов не уникальны")
        if len(arch_ids) < 8:
            errors.append("FAIL: меньше 8 архетипов")
        for a in data["archetypes.json"]["archetypes"]:
            for key in ["risk_permille", "patience_days", "reinvest_permille",
                        "price_aggression_permille", "debt_threshold_permille",
                        "competitor_reaction_permille"]:
                val = a.get(key)
                if not isinstance(val, int) or not (0 <= val <= 1000 if "permille" in key else 1 <= val <= 365):
                    errors.append(f"FAIL: параметр {key} вне границ у {a.get('id')}")

    if "personas.json" in data:
        pers_ids = [p["id"] for p in data["personas.json"]["personas"]]
        if len(pers_ids) != len(set(pers_ids)):
            errors.append("FAIL: id персонажей не уникальны")
        if not (12 <= len(pers_ids) <= 16):
            errors.append(f"FAIL: число персонажей {len(pers_ids)} не в 12-16")
        arch_set = set(arch_ids) if "archetypes.json" in data else set()
        for p in data["personas.json"]["personas"]:
            if p.get("archetype") not in arch_set:
                errors.append(f"FAIL: у {p.get('id')} нет известного архетипа")
            if p.get("ai_mark") != "Управляется ИИ":
                errors.append(f"FAIL: у {p.get('id')} нет пометки «Управляется ИИ»")
            bio = (p.get("bio") or "").lower()
            for phrase in FORBIDDEN_PHRASES:
                if phrase in bio:
                    errors.append(f"FAIL: запрещённая фраза в био {p.get('id')}")
            traits = p.get("traits", {})
            for axis in ["caution", "sociability", "greed", "honesty", "stubbornness"]:
                v = traits.get(axis)
                if not isinstance(v, int) or not (0 <= v <= 1000):
                    errors.append(f"FAIL: ось {axis} вне 0-1000 у {p.get('id')}")

    if "reply_templates.json" in data:
        keys = [t["key"] for t in data["reply_templates.json"]["templates"]]
        if len(keys) != len(set(keys)):
            errors.append("FAIL: ключи шаблонов не уникальны")
        if len(keys) < 30:
            errors.append(f"FAIL: шаблонов {len(keys)} < 30")
        for t in data["reply_templates.json"]["templates"]:
            for ph in t.get("placeholders", []):
                if ph not in ALLOWED_PLACEHOLDERS:
                    errors.append(f"FAIL: запрещённый плейсхолдер {ph} в {t.get('key')}")

    if "limits.json" in data:
        lim = data["limits.json"]["limits"]
        for k, v in lim.items():
            if not isinstance(v, int) or v < 0:
                errors.append(f"FAIL: лимит {k} не целое неотрицательное")
        if data["limits.json"].get("ai_mark_text") != "Управляется ИИ":
            errors.append("FAIL: текст пометки не совпадает")

    if errors:
        print("\n".join(errors))
        sys.exit(1)
    print("OK: все проверки пройдены (balance: draft)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
