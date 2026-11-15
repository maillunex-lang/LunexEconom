"""Read-only health check for isolated LunexEconom endpoints; no restart or writes."""
import argparse
import json
import shutil
import time
import urllib.parse
import urllib.request


def check(url, disk_path="/", min_free_gb=2):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("health checks must use loopback only")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("invalid health URL")
    if parsed.path not in ("", "/health"):
        raise ValueError("only health endpoint is allowed")
    if parsed.port is None or parsed.port in (18767, 18761):
        raise ValueError("production/default port forbidden")
    health = url.rstrip("/") if parsed.path == "/health" else url.rstrip("/") + "/health"
    started = time.monotonic()
    with urllib.request.urlopen(health, timeout=3) as response:
        body = json.load(response)
        if response.status != 200 or not (body.get("ok") is True or body.get("status") == "ok"):
            raise ValueError("unhealthy response")
    free_gb = shutil.disk_usage(disk_path).free / (1024**3)
    return {"healthy": free_gb >= min_free_gb, "latency_ms": round((time.monotonic()-started)*1000, 2),
            "disk_free_gb": round(free_gb, 2), "min_free_gb": min_free_gb,
            "scope": "isolated loopback, read-only"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--disk-path", default="/")
    parser.add_argument("--min-free-gb", type=float, default=2)
    args = parser.parse_args()
    result = check(args.url, args.disk_path, args.min_free_gb)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())