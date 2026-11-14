#!/usr/bin/env python3
"""Stamp the Android build number into the Godot export preset and client/build_info.json.

Every CI build gets a unique, increasing versionCode derived from the commit count, so Android accepts it as an
update, the in-game updater knows what is installed (it reads build_info.json) and release candidates can be
told apart from debug builds. Run from the repository root:  python3 ops/stamp_build.py --count $(git rev-list --count HEAD)
"""
import argparse
import json
import re
import sys
from pathlib import Path

MAX_CODE = 2_100_000_000


def stamp(root, code, name):
    if not 1 <= code <= MAX_CODE:
        raise ValueError("versionCode out of range")
    if not re.fullmatch(r"[0-9A-Za-z._+-]{1,40}", name):
        raise ValueError("unsafe version name")
    presets = Path(root) / "client" / "export_presets.cfg"
    text = presets.read_text(encoding="utf-8")
    text, n_code = re.subn(r"^version/code=.*$", "version/code=%d" % code, text, flags=re.M)
    text, n_name = re.subn(r"^version/name=.*$", 'version/name="%s"' % name, text, flags=re.M)
    if (n_code, n_name) != (1, 1):
        raise ValueError("export preset must contain exactly one version/code and version/name line")
    presets.write_text(text, encoding="utf-8")
    (Path(root) / "client" / "build_info.json").write_text(
        json.dumps({"version_code": code, "version_name": name}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return code, name


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, required=True, help="number of commits (git rev-list --count HEAD)")
    parser.add_argument("--prefix", default="0.3")
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    code, name = stamp(args.root, args.count, "%s.%d" % (args.prefix, args.count))
    print("stamped versionCode=%d versionName=%s" % (code, name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
