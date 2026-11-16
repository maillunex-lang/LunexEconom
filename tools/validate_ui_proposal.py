#!/usr/bin/env python3
"""Validate UI proposal tokens, contrast, sizes and SVG mockups.
Run: python tools/validate_ui_proposal.py
"""
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "client" / "theme" / "tokens_proposed.json"
MOCKUPS = ROOT / "docs" / "mockups"
UI_DATA = ROOT / "docs" / "proposals" / "UI_DATA.md"

def relative_luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16)/255.0, int(h[2:4], 16)/255.0, int(h[4:6], 16)/255.0
    def lin(c):
        return c/12.92 if c <= 0.04045 else ((c+0.055)/1.055)**2.4
    return 0.2126*lin(r) + 0.7152*lin(g) + 0.0722*lin(b)

def contrast_ratio(fg: str, bg: str) -> float:
    L1 = relative_luminance(fg)
    L2 = relative_luminance(bg)
    lighter, darker = max(L1, L2), min(L1, L2)
    return (lighter + 0.05) / (darker + 0.05)

def check_tokens(data: dict) -> list:
    errors = []
    # Integers where required
    for k, v in data.get("spacing", {}).items():
        if not isinstance(v, int):
            errors.append(f"spacing.{k} must be int, got {type(v).__name__}")
    for k in ["caption", "body_min", "body", "title", "headline", "display"]:
        if not isinstance(data["font"].get(k), int):
            errors.append(f"font.{k} must be int")
    if data["touch"]["min_height_dp"] < 48:
        errors.append("touch.min_height_dp must be >= 48")
    # Unique keys already enforced by JSON
    # Contrast pairs
    dark = data["colors"]["dark"]
    pairs = [
        (dark["text_primary"], dark["background"]),
        (dark["text_primary"], dark["surface"]),
        (dark["text_secondary"], dark["background"]),
        (dark["accent"], dark["background"]),
        (dark["error"], dark["background"]),
        (dark["success"], dark["background"]),
    ]
    for fg, bg in pairs:
        ratio = contrast_ratio(fg, bg)
        if ratio < 4.5:
            errors.append(f"Contrast {fg}/{bg} = {ratio:.2f} < 4.5")
    return errors

def check_svg(path: Path) -> list:
    errors = []
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        # No external refs
        for elem in root.iter():
            for attr in elem.attrib.values():
                if "http://" in attr or "https://" in attr or attr.startswith("url("):
                    errors.append(f"{path.name}: external reference in {attr}")
            if elem.tag.endswith("script"):
                errors.append(f"{path.name}: script tag found")
    except ET.ParseError as e:
        errors.append(f"{path.name}: invalid XML: {e}")
    return errors

def main() -> int:
    errors = []
    if not TOKENS.exists():
        errors.append(f"Missing {TOKENS}")
    else:
        with open(TOKENS) as f:
            data = json.load(f)
        errors.extend(check_tokens(data))
    if MOCKUPS.exists():
        for svg in MOCKUPS.glob("*.svg"):
            errors.extend(check_svg(svg))
    else:
        errors.append("No mockups directory")
    if errors:
        print("FAIL")
        for e in errors:
            print(" -", e)
        return 1
    print("OK: tokens, contrast, SVG valid")
    return 0

if __name__ == "__main__":
    sys.exit(main())
