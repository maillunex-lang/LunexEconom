#!/usr/bin/env python3
"""Fail-closed consistency gate for candidate APK/AAB and signed alpha manifest.

This is in addition to external apksigner, aapt and jarsigner checks in CI.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

from alpha_release_plan import alpha_tag
from check_apk_size import check as check_apk_size
from manifest_security import canonical_json, verify_file as verify_signature
from release_version import parse
from verify_apk_cert import verify_file as verify_certificate, verify_report


def hashes_from_sums(path):
    hashes = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(build/lunex\.apk|build/lunex\.aab)", raw)
        if not match or match.group(2) in hashes:
            raise ValueError("SHA256SUMS must contain exactly one APK and one AAB checksum")
        hashes[match.group(2)] = match.group(1).lower()
    if set(hashes) != {"build/lunex.apk", "build/lunex.aab"}:
        raise ValueError("SHA256SUMS is incomplete")
    return hashes


def verify_badging(data, version_tag):
    code, name = parse(version_tag)
    match = re.search(r"^package: name='([^']+)' versionCode='([^']+)' versionName='([^']+)'", data, re.M)
    if not match or match.groups() != ("org.lunex.bashkiria.v2", str(code), name):
        raise ValueError("APK package/version differs from approved alpha tag")
    lines = re.findall(r"^native-code:\s*(.*)$", data, re.M)
    if len(lines) != 1 or re.findall(r"'([^']+)'", lines[0]) != ["arm64-v8a"]:
        raise ValueError("APK must contain only arm64-v8a")


def verify_assets(tag, apk, aab, sums, badging, cert_report, expected_cert=None,
                  manifest=None, signature=None, public_key=None, minimum=None, test_only=False):
    if alpha_tag(tag.removeprefix("v")) != tag:
        raise ValueError("Release tag is not canonical")
    apk, aab = Path(apk), Path(aab)
    hashes = hashes_from_sums(sums)
    check_apk_size(apk)
    for name, file in (("build/lunex.apk", apk), ("build/lunex.aab", aab)):
        if not file.is_file() or not file.stat().st_size:
            raise ValueError("Release file missing or empty: " + name)
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        if digest != hashes[name]:
            raise ValueError("File hash differs from SHA256SUMS: " + name)
    verify_badging(Path(badging).read_text(encoding="utf-8"), tag)
    report = Path(cert_report).read_text(encoding="utf-8")
    if test_only:
        certs = re.findall(r"(?im)^Signer #\d+ certificate SHA-256 digest:\s*([a-f0-9:]+)\s*$", report)
        if len(certs) != 1 or not verify_report(report, certs[0]):
            raise ValueError("Invalid test certificate")
    else:
        if not expected_cert:
            raise ValueError("Pinned owner certificate required")
        verify_certificate(cert_report, expected_cert)
    if (manifest is None) != (signature is None) or (manifest is None) != (public_key is None):
        raise ValueError("Manifest, signature and public key must be provided together")
    if manifest is not None:
        raw = Path(manifest).read_bytes()
        if raw != canonical_json(json.loads(raw)):
            raise ValueError("Noncanonical update.json")
        payload = json.loads(raw)
        code, name = parse(tag)
        expected = {
            "version_code": code,
            "version_name": name,
            "apk_url": "https://rikagro.ru/lunexeconom/v2/download/lunex-" + name + ".apk",
            "size": apk.stat().st_size,
            "sha256": hashes["build/lunex.apk"],
        }
        if any(payload.get(k) != v for k, v in expected.items()):
            raise ValueError("Manifest APK metadata mismatch")
        if not isinstance(payload.get("min_version_code"), int) or not 1 <= payload["min_version_code"] <= code:
            raise ValueError("Manifest min_version_code invalid")
        if minimum is not None and payload["min_version_code"] != int(minimum):
            raise ValueError("Manifest minimum differs from release plan")
        if not isinstance(payload.get("notes"), str) or not 1 <= len(payload["notes"]) <= 300:
            raise ValueError("Manifest notes missing or too long")
        if not verify_signature(manifest, signature, public_key):
            raise ValueError("Manifest RSA signature verification failed")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--apk", required=True)
    ap.add_argument("--aab", required=True)
    ap.add_argument("--sums", required=True)
    ap.add_argument("--badging", required=True)
    ap.add_argument("--cert-report", required=True)
    ap.add_argument("--expected-cert")
    ap.add_argument("--manifest")
    ap.add_argument("--signature")
    ap.add_argument("--public-key")
    ap.add_argument("--minimum")
    ap.add_argument("--test-only", action="store_true")
    a = ap.parse_args()
    verify_assets(a.tag, a.apk, a.aab, a.sums, a.badging, a.cert_report, a.expected_cert,
                  a.manifest, a.signature, a.public_key, a.minimum, a.test_only)
    print("Alpha release assets and manifest verification PASSED; test_only=" + str(a.test_only))


if __name__ == "__main__":
    main()