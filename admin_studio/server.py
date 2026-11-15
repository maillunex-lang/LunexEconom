"""Separate, opt-in World Studio service; never connect to production game database."""
import base64
import hashlib
import hmac
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from game_client import GameAdminError, GameClient
from livepatch import Store
from game_asset_upload import AssetPublisher, NAMES
from art_catalog import ArtCatalog
from model_catalog import ModelCatalog
from world_editor import WorldDrafts
from world_preview import Preview
from urllib.error import URLError, HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
MAX_BODY = 12 * 1024 * 1024
FAIL_LIMIT, FAIL_WINDOW = 10, 300          # failed sign-ins per client address and window
REQUEST_TIMEOUT = 15                       # seconds a client may stall while sending a request (slow-loris guard)
STATIC_TYPES = {"index.html": "text/html", "app.js": "text/javascript", "world.js": "text/javascript", "game.js": "text/javascript", "navigation.js": "text/javascript", "catalog-readonly.js": "text/javascript", "game-art.js": "text/javascript", "art-catalog.js": "text/javascript", "models.js": "text/javascript", "style.css": "text/css"}
LOOPBACK = ("127.0.0.1", "::1")

def handler_factory(store, token, game=None):
    drafts = WorldDrafts(store)
    game = game or GameClient()
    failures = {}
    failures_lock = threading.Lock()
    expected = hashlib.sha256(("Bearer " + token).encode("utf-8")).digest()
    game_art = AssetPublisher(os.environ.get("LUNEX_GAME_ASSETS", "/var/www/rikagro-game/lunexeconom/assets"))
    art_catalog = ArtCatalog(os.environ.get("LUNEX_ART_CATALOG", "/var/www/rikagro-game/lunexeconom/assets/art-catalog"))
    models = ModelCatalog(os.environ.get("LUNEX_STUDIO_MODELS", str(store.root / "models")))
    preview = Preview(os.environ.get("LUNEX_WORLD_PREVIEW_UPSTREAM", "http://127.0.0.1:18767"))
    class Handler(BaseHTTPRequestHandler):
        timeout = REQUEST_TIMEOUT

        def client_ip(self):
            """Address of the person: behind the loopback reverse proxy it comes from X-Real-IP, otherwise from the socket."""
            peer = self.client_address[0]
            return (self.headers.get("X-Real-IP", peer) or peer)[:64] if peer in LOOPBACK else peer

        def throttled(self):
            now = time.time()
            with failures_lock:
                recent = [t for t in failures.get(self.client_ip(), []) if now - t < FAIL_WINDOW]
                failures[self.client_ip()] = recent
                return len(recent) >= FAIL_LIMIT

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
            """Constant-time comparison of SHA-256 digests (bytes: non-ASCII input cannot raise); failures are counted per address."""
            given = hashlib.sha256(self.headers.get("Authorization", "").encode("utf-8", "replace")).digest()
            ok = hmac.compare_digest(given, expected)
            if not ok:
                with failures_lock:
                    failures.setdefault(self.client_ip(), []).append(time.time())
            return ok

        def deny(self):
            return self.send(401, {"error": "unauthorized"})       # the block starts with the NEXT request (see throttled())

        def game_call(self, method, path, query=None, payload=None):
            try:
                return self.send(200, game.request(method, path, query, payload, actor="studio-admin", ip=self.client_ip()))
            except GameAdminError as error:
                return self.send(error.status if error.status in (400, 401, 403, 404, 409, 429, 502, 503) else 502, error.payload)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/art/manifest.json":
                return self.send(200, art_catalog.public_manifest())
            if path == "/health":
                return self.send(200, {"status": "ok", "signing": store.signing_enabled, "game_admin": game.configured})
            if path in ("/patch/manifest.json", "/patch/manifest.sig"):
                text, signature = store.public_manifest()
                body = (text if path.endswith(".json") else (signature or "")).encode("utf-8")
                self.send_response(200 if (path.endswith(".json") or signature) else 404)
                self.send_header("Content-Type", "application/json; charset=utf-8" if path.endswith(".json") else "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path.startswith("/patch/blobs/"):
                filename = path.removeprefix("/patch/blobs/")
                if not re.fullmatch(r"[0-9a-f]{64}\.(png|webp)", filename):
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
            if path in ("/", "/index.html") or path.lstrip("/") in STATIC_TYPES:
                filename = "index.html" if path == "/" else path.lstrip("/")
                data = (STATIC / filename).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", STATIC_TYPES[filename] + "; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if self.throttled():
                return self.send(429, {"error": "rate_limited"})
            if not self.authorized():
                return self.deny()
            query = parse_qs(urlsplit(self.path).query)
            if path in ("/api/catalog/goods", "/api/deposits"):
                # Authenticated read-only relay; upstream must be loopback.
                from urllib.parse import urlencode
                upstream = os.environ.get("LUNEX_STUDIO_READONLY_UPSTREAM", "http://127.0.0.1:18767")
                parsed = urlsplit(upstream)
                if parsed.scheme != "http" or parsed.hostname not in LOOPBACK or parsed.username or parsed.password:
                    return self.send(503, {"error": "invalid_upstream"})
                endpoint = "/catalog/goods" if path.endswith("/goods") else "/deposits"
                params = {}
                if endpoint == "/deposits":
                    try:
                        params = {k: str(int(query[k][0])) for k in ("x0","y0","x1","y1")}
                        if int(params["x0"]) > int(params["x1"]) or int(params["y0"]) > int(params["y1"]):
                            raise ValueError("invalid bounds")
                    except (ValueError, KeyError, IndexError):
                        return self.send(400, {"error": "invalid_bounds"})
                url = upstream.rstrip("/") + endpoint + ("?" + urlencode(params) if params else "")
                try:
                    with urlopen(url, timeout=3) as response:
                        raw = response.read(1024 * 1024 + 1)
                        if len(raw) > 1024 * 1024:
                            return self.send(502, {"error": "response_too_large"})
                        return self.send(200, json.loads(raw))
                except (URLError, HTTPError, TimeoutError, ValueError, OSError):
                    return self.send(503, {"error": "upstream_unavailable"})
            if path.startswith("/api/game/"):
                name = "/admin/" + path.removeprefix("/api/game/")
                return self.game_call("GET", name, {k: v[0] for k, v in query.items() if len(v) == 1})
            match = re.fullmatch(r"/api/releases/(\d{1,9})/manifest", path)
            if match:
                text = store.manifest_text(int(match.group(1)))
                if text is None:
                    return self.send(404, {"error": "revision_not_found"})
                body = text.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/preview/chunk":
                try:
                    cx = int(query["cx"][0]); cy = int(query["cy"][0])
                    return self.send(200, preview.chunk(cx, cy))
                except (ValueError, KeyError, IndexError):
                    return self.send(400, {"error": "invalid_preview_request"})
                except (URLError, TimeoutError, OSError):
                    return self.send(503, {"error": "upstream_unavailable"})
            if path == "/api/cities":
                return self.send(200, {"cities": drafts.cities()})
            if path.startswith("/api/cities/"):
                city_id = path.removeprefix("/api/cities/")
                try:
                    return self.send(200, drafts.city(city_id))
                except ValueError:
                    return self.send(404, {"error": "city_not_found"})
            if path == "/api/releases":
                return self.send(200, {"releases": store.releases()})
            if path == "/api/models":
                return self.send(200, models.manifest())
            if path == "/api/game-art":
                return self.send(200, game_art.manifest())
            if path == "/api/art-catalog":
                return self.send(200, art_catalog.view())
            if path == "/api/assets":
                return self.send(200, {"assets": store.list_assets()})
            if path == "/api/audit":
                return self.send(200, {"audit": store.audit()})
            return self.send(404, {"error": "not_found"})

        def do_POST(self):
            path = urlsplit(self.path).path
            if self.throttled():
                return self.send(429, {"error": "rate_limited"})
            if not self.authorized():
                return self.deny()
            length = self.headers.get("Content-Length", "")
            if not length.isdecimal() or int(length) > MAX_BODY:
                return self.send(413, {"error": "body_limit"})
            try:
                body = json.loads(self.rfile.read(int(length)))
                if path == "/api/preview/check":
                    return self.send(200, preview.collisions(drafts.city(body["city_id"]), body["cx"], body["cy"]))
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
                if path.startswith("/api/game/"):
                    return self.game_call("POST", "/admin/" + path.removeprefix("/api/game/"), None, body)
                if path == "/api/sign":
                    return self.send(200, store.sign(body["revision"], body["signature"], self.client_ip()))
                if path == "/api/rollback-release":
                    return self.send(200, store.rollback(body["revision"], self.client_ip()))
                if path == "/api/publish":
                    return self.send(200, store.publish(self.client_ip()))
                if path == "/api/models":
                    return self.send(201, models.upload(body["name"], body["data_base64"]))
                if path == "/api/game-art":
                    return self.send(201, game_art.publish(body["name"], body["data_base64"]))
                if path == "/api/art-catalog/upload":
                    return self.send(201, art_catalog.upload(body["id"], body["data_base64"]))
                if path == "/api/art-catalog/mode":
                    return self.send(200, art_catalog.set_mode(body["id"], body["mode"]))
                if path == "/api/assets":
                    payload = base64.b64decode(body["data_base64"], validate=True)
                    result = store.add_asset(body["id"], body["category"], body["title"],
                                             body.get("prompt", ""), body["extension"], payload, self.client_ip())
                    return self.send(201, result)
                return self.send(404, {"error": "not_found"})
            except (URLError, TimeoutError, OSError):
                return self.send(503, {"error": "upstream_unavailable"})
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                return self.send(400, {"error": "invalid_request", "detail": str(exc)[:100]})

    return Handler

if __name__ == "__main__":
    token = os.environ.get("LUNEX_ADMIN_TOKEN", "")
    if len(token) < 32:
        raise SystemExit("LUNEX_ADMIN_TOKEN must contain at least 32 characters")
    store = Store(os.environ.get("LUNEX_STUDIO_DATA", "/tmp/lunex-studio-dev"), os.environ.get("LUNEX_STUDIO_PUBLIC_KEY") or None)
    if not store.signing_enabled:
        print("WARNING: LUNEX_STUDIO_PUBLIC_KEY is not set: releases are served UNSIGNED (clients with signature checks will refuse them)", flush=True)
    host = os.environ.get("LUNEX_ADMIN_BIND", "127.0.0.1")
    port = int(os.environ.get("LUNEX_ADMIN_PORT", "18991"))
    print("World Studio listening on", host, port, flush=True)
    ThreadingHTTPServer((host, port), handler_factory(store, token)).serve_forever()