#!/usr/bin/env python3
"""Fail closed when arm64 release exceeds the 99 MiB owner-approved budget."""
import argparse
import json
from pathlib import Path
MAX_APK_BYTES = 99 * 1024 * 1024

def check(apk, max_bytes=MAX_APK_BYTES):
    actual = Path(apk).stat().st_size
    if actual <= 0 or actual > max_bytes:
        raise ValueError(f"APK size {actual} bytes exceeds {max_bytes} bytes")
    return actual

if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("apk")
    p.add_argument("--limit-bytes", type=int, default=MAX_APK_BYTES)
    options=p.parse_args()
    print(json.dumps({"apk":options.apk,"bytes":check(options.apk,options.limit_bytes),"limit_bytes":options.limit_bytes}))
