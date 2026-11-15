#!/usr/bin/env python3
"""Build the Russian-only client catalogue from approved documentation."""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    "docs/content/ui_strings.ru.md",
    "docs/content/update_screen.ru.md",
    "docs/content/notifications.ru.md",
)
KEY = re.compile(r"^[a-z][a-z0-9_.]*$")
PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def collect(root=ROOT):
    strings = {}
    for source in SOURCES:
        for number, line in enumerate((root / source).read_text(encoding="utf-8").splitlines(), 1):
            if "|" not in line:
                continue
            key, text = (piece.strip() for piece in line.split("|", 1))
            if not KEY.fullmatch(key):
                continue
            if not text:
                raise ValueError(f"Empty translation: {source}:{number}: {key}")
            if key in strings:
                raise ValueError(f"Duplicate key {key} in {source}:{number}")
            # Reject incomplete placeholders and typos, no ambiguous braces.
            if re.sub(PLACEHOLDER, "", text).count("{") or re.sub(PLACEHOLDER, "", text).count("}"):
                raise ValueError(f"Malformed placeholder {key} in {source}:{number}")
            strings[key] = text
    return strings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = ROOT / "client/data/strings.json"
    content = json.dumps(collect(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not output.exists() or output.read_text(encoding="utf-8") != content:
            raise SystemExit("strings.json differs from docs: rerun tools/build_strings.py")
        print(f"strings OK: {len(collect())} keys")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        print(f"built {output.relative_to(ROOT)}: {len(collect())} keys")


if __name__ == "__main__":
    main()
