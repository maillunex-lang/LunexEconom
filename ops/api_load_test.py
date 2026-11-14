#!/usr/bin/env python3
"""Bounded API smoke/load probe, strictly loopback only (never production)."""
import argparse
import concurrent.futures
import json
import statistics
import time
import urllib.parse
import urllib.request


def validate_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("only local HTTP test instances are allowed")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("credentials, query and fragments are forbidden")
    if parsed.path not in ("", "/health"):
        raise ValueError("only /health can be load tested")
    if parsed.port is None or parsed.port in (18767, 18761):
        raise ValueError("use a separate explicit test port, not production/default")
    return url.rstrip("/") + ("" if parsed.path == "/health" else "/health")


def probe(url):
    started = time.monotonic()
    with urllib.request.urlopen(url, timeout=3) as resp:
        payload = json.load(resp)
        if resp.status != 200 or payload.get("ok") is not True:
            raise ValueError("unexpected health response")
    return (time.monotonic() - started) * 1000


def run(url, requests=50, workers=5):
    url = validate_url(url)
    if not (1 <= requests <= 500 and 1 <= workers <= 16):
        raise ValueError("load limits exceeded")
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(probe, url) for _ in range(requests)]
        times = []
        errors = 0
        for f in futures:
            try:
                times.append(f.result())
            except Exception:
                errors += 1
    ordered = sorted(times)
    return {"requests": requests, "ok": len(times), "errors": errors,
            "p50_ms": round(statistics.median(times), 2) if times else None,
            "p95_ms": round(ordered[min(len(ordered)-1, int(len(ordered)*0.95))], 2) if times else None}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", required=True, help="http://127.0.0.1:<test-port>/health")
    p.add_argument("--requests", type=int, default=50)
    p.add_argument("--workers", type=int, default=5)
    args = p.parse_args()
    result = run(args.url, args.requests, args.workers)
    print(json.dumps(result))
    if result["errors"]:
        raise SystemExit(1)
