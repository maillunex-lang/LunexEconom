#!/usr/bin/env python3
"""Generate canonical, UNSIGNED update.json. Owner signs separately offline."""
import argparse
from pathlib import Path
from datetime import datetime, timezone
from manifest_security import canonical_json, sha256, validate_https_file_url
from release_version import parse


def make(apk, version, minimum, notes, base):
    apk = Path(apk)
    code, name = parse(version)
    minimum = int(minimum)
    if not 1 <= minimum <= code:
        raise ValueError("min_version_code must be between 1 and current version code")
    url = base.rstrip("/") + "/download/lunex.apk"
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
    ap.add_argument("--base", default=None)
    ap.add_argument("--output", default="build/update.json")
    args = ap.parse_args()
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical_json(make(args.apk, args.version, args.min_code, args.notes, args.base or __import__("project_urls").public_base())))
    print("Unsigned manifest prepared; MUST sign offline:", destination)
