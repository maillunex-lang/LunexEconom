#!/usr/bin/env python3
"""Monotonically sortable Android versionCodes from strict semantic tags."""
import argparse
import re
from pathlib import Path


def parse(tag):
    match = re.fullmatch(r"v([0-9]+)\.([0-9]+)\.([0-9]+)", tag)
    if not match:
        raise ValueError("Tag must match vMAJOR.MINOR.PATCH")
    major, minor, patch = map(int, match.groups())
    if not 0 <= major <= 2000 or not 0 <= minor < 1000 or not 0 <= patch < 1000 or not any((major, minor, patch)):
        raise ValueError("Version numbers out of range")
    code = major * 1_000_000 + minor * 1000 + patch
    if code > 2_100_000_000:
        raise ValueError("Android versionCode overflow")
    return code, tag[1:]


def validate_monotonic(tag, previous_tags):
    code, _ = parse(tag)
    for previous in previous_tags:
        if not previous or previous == tag:
            continue
        try:
            prior_code, _ = parse(previous)
        except ValueError:
            continue
        if code <= prior_code:
            raise ValueError(f"Version {tag} must be newer than {previous}")


def validate_monotonic(tag, previous_tags):
    code, _ = parse(tag)
    for previous in previous_tags:
        if not previous or previous == tag:
            continue
        try:
            prior_code, _ = parse(previous)
        except ValueError:
            continue
        if code <= prior_code:
            raise ValueError(f"Version {tag} must be newer than {previous}")


def stamp(preset, tag, info, earlier_tags=()):
    validate_monotonic(tag, earlier_tags)
    code, name = parse(tag)
    path = Path(preset)
    text = path.read_text()
    text, n = re.subn(r'(?m)^version/code=\d+$', f'version/code={code}', text)
    if n != 1:
        raise ValueError("Export preset must have exactly one version/code")
    text, n = re.subn(r'(?m)^version/name="[^"]*"$', f'version/name="{name}"', text)
    if n != 1:
        raise ValueError("Export preset must have exactly one version/name")
    path.write_text(text)
    import json
    Path(info).write_text(json.dumps(dict(version_code=code, version_name=name), indent=2) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--preset", default="client/export_presets.cfg")
    ap.add_argument("--info", default="client/build_info.json")
    ap.add_argument("--previous-tags", help="File with already created semver release tags")
    opts = ap.parse_args()
    previous = Path(opts.previous_tags).read_text().splitlines() if opts.previous_tags else ()
    stamp(opts.preset, opts.tag, opts.info, previous)
