#!/usr/bin/env python3
"""Generate canonical, UNSIGNED update.json. Owner signs separately offline."""
import argparse
from pathlib import Path
from datetime import datetime, timezone
from manifest_security import canonical_json, sha256, validate_https_file_url
from release_version import parse
from check_apk_size import check as check_apk_size

ALPHA_BASE = "https://rikagro.ru/lunexeconom/v2"
from check_apk_size import check as check_apk_size

ALPHA_BASE = "https://rikagro.ru/lunexeconom/v2"


def make(apk, version, minimum, notes, base, apk_name=None):
    apk = Path(apk)
    code, name = parse(version)
    minimum = int(minimum)
    check_apk_size(apk)
    check_apk_size(apk)
    if not 1 <= minimum <= code:
        raise ValueError("min_version_code must be between 1 and current version code")
    if apk_name is None:
        apk_name = f"lunex-{name}.apk" if version.startswith("v0.1.") else "lunex.apk"
    if not (apk_name == "lunex.apk" or apk_name == f"lunex-{name}.apk"):
        raise ValueError("APK filename does not match version")
    url = base.rstrip("/") + "/download/" + apk_name
    if not validate_https_file_url(url, base):
        raise ValueError("APK link must be an HTTPS URL under the public base")
    return {
        "version_code": code,
        "version_name": name,
        "min_version_code": minimum,
        "apk_url": url,
        "size": apk.stat().st_size,
        "sha256": sha256(apk),
        "notes": notes,
        "released": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("apk")
    ap.add_argument("--version", required=True)
    ap.add_argument("--min-code", type=int, required=True)
    ap.add_argument("--notes", default="Обновление игры")
    ap.add_argument("--apk-name", help="Versioned APK name on V2 website")
    ap.add_argument("--apk-name", help="Versioned APK name on V2 website")
    ap.add_argument("--base", default=None)
    ap.add_argument("--output", default="build/update.json")
    args = ap.parse_args()
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical_json(make(args.apk, args.version, args.min_code, args.notes, args.base or ALPHA_BASE, args.apk_name)))
    print("Unsigned manifest prepared; MUST sign offline:", destination)
