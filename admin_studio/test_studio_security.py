"""Studio hardening: image headers, signed releases, sign-in throttling, game admin relay."""
import base64
import http.client
import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import fixtures
import sign_release
from game_client import GameClient
from livepatch import MAX_DIMENSION, Store, image_dimensions
from server import handler_factory

TOKEN = "s" * 40
GAME_TOKEN = "g" * 40
HAVE_OPENSSL = subprocess.run(["openssl", "version"], capture_output=True).returncode == 0


class Fake(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *args):
        pass

    def reply(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        Fake.seen.append(("GET", self.path, dict(self.headers)))
        self.reply(200 if self.headers.get("Authorization") == "Bearer " + GAME_TOKEN else 401, {"ok": True, "path": self.path})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Fake.seen.append(("POST", self.path, dict(self.headers), body))
        self.reply(200, {"ok": True})


class Base(unittest.TestCase):
    public_key = None

    def start(self, public_key=None, game=None):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name, public_key)
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory(self.store, TOKEN, game or GameClient("http://127.0.0.1:9", GAME_TOKEN)))
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.port = self.http.server_address[1]

    def tearDown(self):
        if hasattr(self, "http"):
            self.http.shutdown()
            self.http.server_close()
            self.temp.cleanup()

    def call(self, method, path, body=None, token=TOKEN, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = dict(headers or {})
        if token is not None:
            h["Authorization"] = "Bearer " + token
        raw = None if body is None else json.dumps(body).encode()
        if raw is not None:
            h["Content-Type"] = "application/json"
        conn.request(method, path, body=raw, headers=h)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, data

    def upload(self, name="farm_1", payload=None, ext="png"):
        payload = payload or fixtures.png()
        return self.call("POST", "/api/assets", {"id": name, "category": "agriculture", "title": "T", "prompt": "", "extension": ext,
                                                 "data_base64": base64.b64encode(payload).decode()})


class ImageHeaderTests(Base):
    def test_valid_images_report_their_size(self):
        self.assertEqual(image_dimensions("png", fixtures.png(8, 6)), (8, 6))
        self.assertEqual(image_dimensions("webp", fixtures.webp_vp8x(300, 200)), (300, 200))
        self.assertEqual(image_dimensions("webp", fixtures.webp_vp8l(64, 32)), (64, 32))
        self.assertEqual(image_dimensions("webp", fixtures.webp_vp8(128, 96)), (128, 96))

    def test_decompression_bombs_are_rejected_by_the_header_alone(self):
        for width, height in ((40000, 40000), (MAX_DIMENSION + 1, 10), (10, MAX_DIMENSION + 1), (2048, 2048 + 1), (0, 10)):
            with self.assertRaises(ValueError, msg=(width, height)):
                image_dimensions("png", fixtures.png_header_only(width, height))
        with self.assertRaises(ValueError):
            image_dimensions("webp", fixtures.webp_vp8x(16000, 16000))
        with self.assertRaises(ValueError):
            image_dimensions("webp", fixtures.webp_vp8l(3000, 10))

    def test_garbage_and_truncated_headers_are_rejected(self):
        for ext, data in (("png", b"\x89PNG\r\n\x1a\n" + b"x" * 20), ("png", b"short"), ("webp", b"RIFF" + b"\x00" * 30), ("webp", b"RIFF\x00\x00\x00\x00WEBPVP8Z" + b"\x00" * 20)):
            with self.assertRaises(ValueError):
                image_dimensions(ext, data)

    def test_upload_refuses_a_bomb_over_http(self):
        self.start()
        self.assertEqual(self.upload("ok_asset")[0], 201)
        status, body = self.upload("bomb_asset", fixtures.png_header_only(40000, 40000))
        self.assertEqual(status, 400)
        self.assertEqual(self.store.list_assets().__len__(), 1)


@unittest.skipUnless(HAVE_OPENSSL, "openssl command line not available")
class SignedReleaseTests(Base):
    def setUp(self):
        self.keys = tempfile.TemporaryDirectory()
        self.private = Path(self.keys.name, "private.pem")
        self.public = Path(self.keys.name, "public.pem")
        subprocess.run(["openssl", "genrsa", "-out", str(self.private), "2048"], check=True, capture_output=True)
        subprocess.run(["openssl", "rsa", "-in", str(self.private), "-pubout", "-out", str(self.public)], check=True, capture_output=True)
        self.other = Path(self.keys.name, "other.pem")
        subprocess.run(["openssl", "genrsa", "-out", str(self.other), "2048"], check=True, capture_output=True)

    def tearDown(self):
        super().tearDown()
        self.keys.cleanup()

    def sign(self, key, message):
        return base64.b64encode(sign_release.sign_bytes(key, message)).decode()

    def test_unsigned_release_is_not_served_when_a_key_is_configured(self):
        self.start(self.public)
        self.upload()
        self.assertEqual(self.call("POST", "/api/publish", {})[0], 200)
        status, body = self.call("GET", "/patch/manifest.json", token=None)
        self.assertEqual(json.loads(body)["revision"], 0)
        self.assertEqual(self.call("GET", "/patch/manifest.sig", token=None)[0], 404)

    def test_signature_flow_and_the_bytes_clients_verify(self):
        self.start(self.public)
        self.upload()
        self.call("POST", "/api/publish", {})
        _, raw = self.call("GET", "/api/releases/1/manifest")
        status, _ = self.call("POST", "/api/sign", {"revision": 1, "signature": self.sign(self.other, raw)})
        self.assertEqual(status, 400)                                    # a signature from another key is refused
        status, _ = self.call("POST", "/api/sign", {"revision": 1, "signature": "!!not-base64!!"})
        self.assertEqual(status, 400)
        status, _ = self.call("POST", "/api/sign", {"revision": 9, "signature": self.sign(self.private, raw)})
        self.assertEqual(status, 400)
        status, _ = self.call("POST", "/api/sign", {"revision": 1, "signature": self.sign(self.private, raw)})
        self.assertEqual(status, 200)
        status, served = self.call("GET", "/patch/manifest.json", token=None)
        _, signature = self.call("GET", "/patch/manifest.sig", token=None)
        self.assertEqual(served, raw)                                    # byte-identical to what was signed
        message, sig = Path(self.keys.name, "m"), Path(self.keys.name, "s")
        message.write_bytes(served)
        sig.write_bytes(base64.b64decode(signature))
        check = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(self.public), "-signature", str(sig), str(message)], capture_output=True)
        self.assertEqual(check.returncode, 0)
        message.write_bytes(served.replace(b'"revision":1', b'"revision":2'))
        tampered = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(self.public), "-signature", str(sig), str(message)], capture_output=True)
        self.assertNotEqual(tampered.returncode, 0)                      # any change to the manifest breaks the signature

    def test_rollback_needs_a_fresh_signature_and_the_old_signed_release_keeps_serving(self):
        self.start(self.public)
        self.upload()
        self.call("POST", "/api/publish", {})
        _, raw = self.call("GET", "/api/releases/1/manifest")
        self.call("POST", "/api/sign", {"revision": 1, "signature": self.sign(self.private, raw)})
        self.call("POST", "/api/rollback-release", {"revision": 1})      # creates revision 2, unsigned
        _, served = self.call("GET", "/patch/manifest.json", token=None)
        self.assertEqual(json.loads(served)["revision"], 1)
        releases = json.loads(self.call("GET", "/api/releases")[1])["releases"]
        self.assertEqual({r["revision"]: r["signed"] for r in releases}, {1: True, 2: False})

    def test_offline_signing_tool_end_to_end(self):
        self.start(self.public)
        self.upload()
        self.call("POST", "/api/publish", {})
        os.environ["LUNEX_ADMIN_TOKEN"] = TOKEN
        try:
            code = sign_release.main(["--studio", "http://127.0.0.1:%d" % self.port, "--key", str(self.private), "--revision", "1"])
        finally:
            del os.environ["LUNEX_ADMIN_TOKEN"]
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(self.call("GET", "/patch/manifest.json", token=None)[1])["revision"], 1)

    def test_signing_is_refused_when_not_configured(self):
        self.start(None)
        self.upload()
        self.call("POST", "/api/publish", {})
        self.assertEqual(self.call("POST", "/api/sign", {"revision": 1, "signature": "AAAA"})[0], 400)
        self.assertFalse(json.loads(self.call("GET", "/health", token=None)[1])["signing"])


class AccessHardeningTests(Base):
    def test_sign_in_failures_are_throttled_per_address(self):
        self.start()
        for _ in range(10):
            self.assertEqual(self.call("GET", "/api/assets", token="wrong" * 8)[0], 401)
        self.assertEqual(self.call("GET", "/api/assets", token="wrong" * 8)[0], 429)
        self.assertEqual(self.call("GET", "/api/assets")[0], 429)        # the right token waits out the window too
        self.assertEqual(self.call("GET", "/api/assets", token="wrong" * 8, headers={"X-Real-IP": "203.0.113.9"})[0], 401)   # another address is unaffected

    def test_non_ascii_authorization_header_is_a_plain_401(self):
        self.start()
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest("GET", "/api/assets")
        conn.putheader("Authorization", "Bearer éè")
        conn.endheaders()
        self.assertEqual(conn.getresponse().status, 401)
        conn.close()

    def test_handler_has_a_read_timeout(self):
        self.start()
        self.assertEqual(handler_factory(self.store, TOKEN).timeout, 15)

    def test_audit_records_the_client_address(self):
        self.start()
        self.call("POST", "/api/assets", {"id": "farm_1", "category": "agriculture", "title": "T", "prompt": "", "extension": "png",
                                          "data_base64": base64.b64encode(fixtures.png()).decode()}, headers={"X-Real-IP": "198.51.100.4"})
        self.call("POST", "/api/publish", {}, headers={"X-Real-IP": "198.51.100.4"})
        audit = json.loads(self.call("GET", "/api/audit")[1])["audit"]
        self.assertTrue(all("198.51.100.4" in row["details"] for row in audit))

    def test_unauthenticated_paths_are_limited_to_the_public_patch_files(self):
        self.start()
        self.assertEqual(self.call("GET", "/api/game/overview", token=None)[0], 401)
        self.assertEqual(self.call("GET", "/patch/blobs/../../etc/passwd", token=None)[0], 404)
        self.assertEqual(self.call("GET", "/patch/blobs/" + "a" * 64 + ".png", token=None)[0], 404)


class GameRelayTests(Base):
    def setUp(self):
        Fake.seen = []
        self.fake = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=self.fake.serve_forever, daemon=True).start()
        self.upstream = "http://127.0.0.1:%d" % self.fake.server_address[1]

    def tearDown(self):
        super().tearDown()
        self.fake.shutdown()
        self.fake.server_close()

    def test_reads_are_relayed_with_the_game_token_not_the_studio_token(self):
        self.start(None, GameClient(self.upstream, GAME_TOKEN))
        status, body = self.call("GET", "/api/game/players?q=ali")
        self.assertEqual(status, 200)
        method, path, headers = Fake.seen[-1][:3]
        self.assertEqual(path, "/admin/players?q=ali")
        self.assertEqual(headers["Authorization"], "Bearer " + GAME_TOKEN)
        self.assertNotIn(TOKEN, json.dumps(headers))
        self.assertEqual(headers["X-Admin-Actor"], "studio-admin")

    def test_changes_are_relayed_and_unknown_paths_are_refused(self):
        self.start(None, GameClient(self.upstream, GAME_TOKEN))
        self.assertEqual(self.call("POST", "/api/game/ban", {"username": "alice", "reason": "тест"})[0], 200)
        self.assertEqual(Fake.seen[-1][1], "/admin/ban")
        self.assertEqual(Fake.seen[-1][3]["username"], "alice")
        before = len(Fake.seen)
        self.assertEqual(self.call("GET", "/api/game/../wallet")[0], 404)
        self.assertEqual(self.call("POST", "/api/game/wipe-everything", {})[0], 404)
        self.assertEqual(len(Fake.seen), before)                         # nothing reached the game server

    def test_city_generation_routes_are_relayed(self):
        self.start(None, GameClient(self.upstream, GAME_TOKEN))
        self.assertEqual(self.call("GET", "/api/game/cities")[0], 200)
        self.assertEqual(Fake.seen[-1][1], "/admin/cities")
        self.assertEqual(self.call("POST", "/api/game/cities/seed", {"city_id": "ufa", "dry_run": True})[0], 200)
        self.assertEqual((Fake.seen[-1][1], Fake.seen[-1][3]["city_id"]), ("/admin/cities/seed", "ufa"))
        self.assertEqual(self.call("GET", "/api/game/cities/seed")[0], 404)         # not a readable route

    def test_not_configured_and_unreachable_upstream(self):
        self.start(None, GameClient(self.upstream, ""))
        self.assertEqual(self.call("GET", "/api/game/overview")[0], 503)
        self.http.shutdown(); self.http.server_close(); self.temp.cleanup()
        self.start(None, GameClient("http://127.0.0.1:9", GAME_TOKEN))
        self.assertEqual(self.call("GET", "/api/game/overview")[0], 503)

    def test_studio_requires_its_own_token_for_every_game_route(self):
        self.start(None, GameClient(self.upstream, GAME_TOKEN))
        self.assertEqual(self.call("GET", "/api/game/overview", token=None)[0], 401)
        self.assertEqual(self.call("POST", "/api/game/ban", {"username": "a", "reason": "b"}, token=None)[0], 401)
        self.assertEqual(Fake.seen, [])


if __name__ == "__main__":
    unittest.main()
