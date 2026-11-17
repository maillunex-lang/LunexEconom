#!/usr/bin/env python3
"""Validate the AI source index without importing game modules or contacting services."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/source_manifest.json"


def validate():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    errors = []
    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    components = data.get("components")
    if not isinstance(components, list) or not components:
        return ["components must be a nonempty list"]
    ids = set()
    for index, component in enumerate(components):
        name = component.get("id", f"item-{index}")
        if not isinstance(name, str) or not name:
            errors.append(f"component {index}: missing id")
        elif name in ids:
            errors.append(f"duplicate id: {name}")
        ids.add(name)
        if not component.get("name_ru"):
            errors.append(f"{name}: missing name_ru")
        if component.get("kind") not in data.get("status_semantics", {}):
            errors.append(f"{name}: unrecognized kind")
        for field in ("paths", "test_paths"):
            paths = component.get(field)
            if not isinstance(paths, list) or not paths:
                errors.append(f"{name}: {field} must be a nonempty list")
                continue
            for value in paths:
                if not isinstance(value, str) or not value:
                    errors.append(f"{name}: invalid path in {field}")
                    continue
                candidate = (ROOT / value).resolve()
                if not candidate.is_relative_to(ROOT):
                    errors.append(f"{name}: path escapes repository: {value}")
                elif not candidate.exists():
                    errors.append(f"{name}: missing {field} path: {value}")
    return errors


if __name__ == "__main__":
    problems = validate()
    for problem in problems:
        print("ERROR:", problem)
    if problems:
        raise SystemExit(1)
    print("OK: source manifest paths and schema")
