#!/usr/bin/env python3
"""Strict and side-effect-free planning for an Android V2 alpha release."""
import argparse
import json
import re
from pathlib import Path
from release_version import parse

ALPHA_VERSION = re.compile(r"0\.1\.(0|[1-9][0-9]{0,2})\Z")
CYRILLIC = re.compile(r"[А-Яа-яЁё]")


def alpha_tag(version):
    if not ALPHA_VERSION.fullmatch(version):
        raise ValueError("Alpha version must be 0.1.N, where N is 0..999")
    tag = "v" + version
    parse(tag)
    return tag


def select_previous(tags):
    valid = []
    for tag in tags:
        if tag.startswith("v") and ALPHA_VERSION.fullmatch(tag[1:]):
            valid.append((parse(tag)[0], tag))
    return max(valid, default=(None, None))


def plan(version, notes, published_tags, reserved_tags, minimum=""):
    tag = alpha_tag(version)
    code, _ = parse(tag)
    if not isinstance(notes, str) or not 1 <= len(notes) <= 300 or not notes.strip() or not CYRILLIC.search(notes):
        raise ValueError("Russian release notes must be 1..300 characters and include Cyrillic")
    previous_code, previous_tag = select_previous(published_tags)
    if previous_code is not None and code <= previous_code:
        raise ValueError("Alpha version must be newer than previous published release")
    reserved_code, reserved_tag = select_previous(reserved_tags)
    if reserved_code is not None and code <= reserved_code:
        raise ValueError("Alpha version must be newer than existing alpha tags")
    if minimum == "" or minimum is None:
        min_code = previous_code if previous_code is not None else 1
    else:
        if not re.fullmatch(r"[1-9][0-9]*", str(minimum)):
            raise ValueError("min_version_code must be a positive integer")
        min_code = int(minimum)
    if not 1 <= min_code <= code:
        raise ValueError("min_version_code is outside 1..new versionCode")
    return {"version_tag": tag, "version_name": version, "version_code": code,
            "min_version_code": min_code, "previous_tag": previous_tag, "notes": notes}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--notes", required=True)
    ap.add_argument("--min-version-code", default="")
    ap.add_argument("--published-tags", required=True)
    ap.add_argument("--reserved-tags", required=True)
    ap.add_argument("--github-output")
    ap.add_argument("--test-only", action="store_true")
    args = ap.parse_args()
    published = Path(args.published_tags).read_text().splitlines()
    reserved = Path(args.reserved_tags).read_text().splitlines()
    version = args.version
    if args.test_only and version == "auto":
        latest, _ = select_previous(published + reserved)
        next_patch = 0 if latest is None else latest - 1000 + 1
        if not 0 <= next_patch <= 999:
            raise ValueError("No free alpha patch version for CI test")
        version = f"0.1.{next_patch}"
    result = plan(version, args.notes, published, reserved, args.min_version_code)
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as fd:
            for key in ("version_tag", "version_name", "version_code", "min_version_code"):
                fd.write(f"{key}={result[key]}\n")
    print(json.dumps({key: value for key, value in result.items() if key != "notes"}, ensure_ascii=False))


if __name__ == "__main__":
    main()