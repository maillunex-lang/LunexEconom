#!/usr/bin/env python3
"""Compare apksigner SHA-256 certificate against pinned expected fingerprint."""
import argparse
import re
from pathlib import Path


def normalize(data):
    stripped = re.sub(r"[^0-9a-fA-F]", "", data)
    if not re.fullmatch(r"[0-9a-fA-F]{64}", stripped):
        raise ValueError("Expected a 32-byte SHA-256 fingerprint")
    return stripped.lower()


def verify_report(report, expected):
    lines = re.findall(r"(?im)^Signer #\d+ certificate SHA-256 digest:\s*([a-f0-9:]+)\s*$", report)
    if len(lines) != 1:
        raise ValueError("Expected exactly one apksigner certificate SHA-256")
    return normalize(lines[0]) == normalize(expected)


def verify_file(report, expected_file):
    data = Path(expected_file).read_text().strip()
    if not data or data.startswith("#"):
        raise ValueError("Pinned certificate fingerprint is missing")
    if not verify_report(Path(report).read_text(), data):
        raise ValueError("APK signed with an unapproved certificate")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("expected")
    args = ap.parse_args()
    verify_file(args.report, args.expected)
    print("APK certificate SHA-256 matches allowed release certificate")
