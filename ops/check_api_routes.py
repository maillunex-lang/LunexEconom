#!/usr/bin/env python3
"""Probe all GET/POST API routes, rejecting HTML nginx 404 pages.

POST uses an empty body to exercise routing without creating entities.
"""
import argparse
import ast
import concurrent.futures
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

DEFAULT_URL = "https://rikagro.ru/lunexeconom/api"
GAME_SERVER = Path(__file__).resolve().parents[1] / "server" / "game_server.py"
ACCEPTABLE = {200, 201, 400, 401, 403, 404, 405, 409, 422, 429}


def discover_routes(source=GAME_SERVER):
    tree = ast.parse(Path(source).read_text(encoding="utf-8"))
    routes = {"GET": set(), "POST": set()}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Handler":
            for member in node.body:
                if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if member.name not in ("do_GET", "do_POST", "_economy_post"):
                    continue
                method = "GET" if member.name == "do_GET" else "POST"
                for expr in ast.walk(member):
                    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
                        if expr.value.startswith("/") and len(expr.value) > 1:
                            routes[method].add(expr.value)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "ECONOMY_POST"
            for target in node.targets
        ):
            if isinstance(node.value, ast.Dict):
                for key in node.value.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        routes["POST"].add(key.value)
    if "/health" not in routes["GET"] or "/auth/register" not in routes["POST"]:
        raise RuntimeError("Cannot discover game_server.py API routes reliably")
    return {method: sorted(paths) for method, paths in routes.items()}


def probe(base_url, method, path, timeout=8):
    base = base_url.rstrip("/")
    url = base + path
    # Empty POST body triggers the server's safe invalid_body response.
    request = urllib.request.Request(
        url, data=b"" if method == "POST" else None,
        method=method, headers={"Accept": "application/json", "User-Agent": "LunexEconom-route-check/1"},
    )
    try:
        try:
            response = urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            code = response.status
            content_type = response.headers.get("Content-Type", "").lower()
            body = response.read(4096).lstrip()
        looks_html = body.lower().startswith((b"<!doctype html", b"<html"))
        is_json = "application/json" in content_type
        if not is_json and not looks_html:
            try:
                json.loads(body.decode("utf-8"))
                is_json = True
            except (ValueError, UnicodeError):
                pass
        good = code in ACCEPTABLE and is_json and not looks_html
        reason = "" if good else (
            "HTML response (possible nginx 404)" if looks_html else
            "non-JSON API response" if not is_json else
            "unexpected HTTP status"
        )
        return {"method": method, "route": path, "status": code, "ok": good, "error": reason}
    except (OSError, urllib.error.URLError, ValueError) as error:
        return {"method": method, "route": path, "status": None, "ok": False,
                "error": type(error).__name__}


def check(base_url, routes=None, timeout=8, workers=3):
    found = discover_routes() if routes is None else routes
    entries = [(method, path) for method in ("GET", "POST") for path in found[method]]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(probe, base_url, method, path, timeout) for method, path in entries]
        return [future.result() for future in futures]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check nginx public API routing without mutations")
    parser.add_argument("--base-url", default=DEFAULT_URL)
    parser.add_argument("--timeout", type=float, default=8)
    args = parser.parse_args(argv)
    if not args.base_url.startswith("https://") and not args.base_url.startswith("http://127.0.0.1"):
        parser.error("HTTPS required for public checks")
    results = check(args.base_url, timeout=args.timeout)
    for item in results:
        label = "PASS" if item["ok"] else "FAIL"
        print("%s %-4s %-27s %s %s" % (
            label, item["method"], item["route"], item["status"], item["error"],
        ))
    errors = sum(not result["ok"] for result in results)
    print("Checked %d routes, %d failed" % (len(results), errors))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
