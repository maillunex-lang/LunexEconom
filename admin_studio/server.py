"""Separate, opt-in World Studio service; never connect to production game database."""
import base64
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from livepatch import Store
from world_editor import WorldDrafts

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
MAX_BODY = 12 * 1024 * 1024

def handler_factory(store, token):
    drafts = WorldDrafts(store)
    class Handler(BaseHTTPRequestHandler):
        def send(self, code, obj):
            raw = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def authorized(self):
            return hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/health":
                return self.send(200, {"status": "ok"})
            if path == "/patch/manifest.json":
                return self.send(200, store.manifest())
            if path.startswith("/patch/blobs/"):
                filename = path.removeprefix("/patch/blobs/")
                if not __import__("re").fullmatch(r"[0-9a-f]{64}\.(png|webp)", filename):
                    return self.send(404, {"error": "not_found"})
                target = store.root / "blobs" / filename
                if not target.is_file():
                    return self.send(404, {"error": "not_found"})
                data = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png" if filename.endswith(".png") else "image/webp")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "public, max-age=31536000, immutable")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)
                return
            if path in ("/", "/index.html", "/app.js", "/world.js", "/style.css"):
                filename = "index.html" if path == "/" else path.lstrip("/")
                data = (STATIC / filename).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", {"index.html":"text/html","app.js":"text/javascript","world.js":"text/javascript","style.css":"text/css"}[filename] + "; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if not self.authorized():
                return self.send(401, {"error": "unauthorized"})
            if path == "/api/cities":
                return self.send(200, {"cities": drafts.cities()})
            if path.startswith("/api/cities/"):
                city_id = path.removeprefix("/api/cities/")
                try:
                    return self.send(200, drafts.city(city_id))
                except ValueError:
                    return self.send(404, {"error": "city_not_found"})
            if path == "/api/assets":
                return self.send(200, {"assets": store.list_assets()})
            if path == "/api/audit":
                return self.send(200, {"audit": store.audit()})
            return self.send(404, {"error": "not_found"})

        def do_POST(self):
            path = urlsplit(self.path).path
            if not self.authorized():
                return self.send(401, {"error": "unauthorized"})
            length = self.headers.get("Content-Length", "")
            if not length.isdecimal() or int(length) > MAX_BODY:
                return self.send(413, {"error": "body_limit"})
            try:
                body = json.loads(self.rfile.read(int(length)))
                if path == "/api/cities":
                    drafts.save_city(body["id"], body["title"], body["settings"])
                    return self.send(200, drafts.city(body["id"]))
                if path == "/api/buildings":
                    return self.send(201, drafts.place(body["city_id"], body["kind"], body["x"], body["y"]))
                if path == "/api/buildings/remove":
                    drafts.remove(body["city_id"], body["building_id"])
                    return self.send(200, {"removed": True})
                if path == "/api/forecast":
                    return self.send(200, drafts.forecast(body["city_id"], body["months"]))
                if path == "/api/export-city":
                    return self.send(200, drafts.export(body["city_id"]))
                if path == "/api/publish":
                    return self.send(200, store.publish())
                if path == "/api/assets":
                    payload = base64.b64decode(body["data_base64"], validate=True)
                    result = store.add_asset(body["id"], body["category"], body["title"],
                                             body.get("prompt", ""), body["extension"], payload)
                    return self.send(201, result)
                return self.send(404, {"error": "not_found"})
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                return self.send(400, {"error": "invalid_request", "detail": str(exc)[:100]})

    return Handler

if __name__ == "__main__":
    token = os.environ.get("LUNEX_ADMIN_TOKEN", "")
    if len(token) < 32:
        raise SystemExit("LUNEX_ADMIN_TOKEN must contain at least 32 characters")
    store = Store(os.environ.get("LUNEX_STUDIO_DATA", "/tmp/lunex-studio-dev"))
    host = os.environ.get("LUNEX_ADMIN_BIND", "127.0.0.1")
    port = int(os.environ.get("LUNEX_ADMIN_PORT", "18991"))
    print("World Studio listening on", host, port, flush=True)
    ThreadingHTTPServer((host, port), handler_factory(store, token)).serve_forever()
