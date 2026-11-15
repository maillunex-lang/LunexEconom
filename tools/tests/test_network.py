"""Ephemeral TLS fake-server integration test for the Godot update/content pipeline."""
import hashlib
import ipaddress
import os
import re
import ssl
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import zlib
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from manifest_security import canonical_json, sign_file, sha256
from build_packs import build

GODOT = os.environ.get("GODOT", "/opt/game-tools/godot/4.7.2-stable/Godot_v4.7.2-stable_linux.x86_64")
ROOT = Path(__file__).resolve().parents[2]


def png_chunk(name, body):
    return struct.pack(">I", len(body)) + name + body + struct.pack(">I", zlib.crc32(name + body) & 0xffffffff)


PNG = (b"\x89PNG\r\n\x1a\n" +
       png_chunk(b"IHDR", struct.pack(">2I5B", 1, 1, 8, 2, 0, 0, 0)) +
       png_chunk(b"IDAT", zlib.compress(b"\0\xff\0\0")) +
       png_chunk(b"IEND", b""))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        data = self.server.files.get(self.path)
        if data is None:
            self.send_error(404)
            return
        if self.path.endswith(".apk") or self.path.endswith(".pck"):
            hdr = self.headers.get("Range", "")
            match = re.fullmatch(r"bytes=(\d+)-(\d+)", hdr)
            if not match:
                self.send_error(416)
                return
            start, end = map(int, match.groups())
            if end >= len(data) or start > end:
                self.send_error(416)
                return
            self.server.range_starts.append(start)
            chunk = data[start:end + 1]
            self.send_response(206)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
            self.send_header("Content-Length", str(len(chunk)))
            self.end_headers()
            if self.path.endswith(".apk") and self.server.break_once:
                self.server.break_once = False
                self.wfile.write(chunk[:8192])
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            self.wfile.write(chunk)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json" if self.path.endswith(".json") else "text/plain")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        pass


class GodotHTTPSIntegration(unittest.TestCase):
    def test_https_signed_manifest_and_resumable_assets(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        with tempfile.TemporaryDirectory(prefix="lunex-smoke-") as temp:
            temp = Path(temp)
            source = temp / "content" / "core_start"
            source.mkdir(parents=True)
            (source / "icon.png").write_bytes(PNG)
            manifest_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            key_file = temp / "manifest-private.pem"
            pub_file = temp / "manifest-public.pem"
            key_file.write_bytes(manifest_key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            pub_file.write_bytes(manifest_key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
            tls_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            identity = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
            certificate = (x509.CertificateBuilder()
                           .subject_name(identity).issuer_name(identity).public_key(tls_key.public_key())
                           .serial_number(x509.random_serial_number())
                           .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
                           .not_valid_after(datetime.now(timezone.utc) + timedelta(days=2))
                           .add_extension(x509.SubjectAlternativeName([
                               x509.DNSName("localhost"),
                               x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
                           .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                           .sign(tls_key, hashes.SHA256()))
            cert_file = temp / "test_tls.crt"
            tls_file = temp / "test_tls.key"
            cert_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
            tls_file.write_bytes(tls_key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            server.files = {}
            server.range_starts = []
            server.break_once = True
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(str(cert_file), str(tls_file))
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"https://localhost:{server.server_address[1]}/lunexeconom"
                payload = b"LUNEX-" + b"x" * 620000
                pack_info = build(temp / "content", temp / "packs", "1.0.0", base, GODOT)
                pack = temp / "packs" / "core_start-1.0.0.pck"
                path = temp / "update.json"
                path.write_bytes(canonical_json({
                    "version_code": 10, "version_name": "0.0.10", "min_version_code": 5,
                    "apk_url": base + "/download/lunex.apk", "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "notes": "Важное обновление", "released": "2026-11-15T12:00:00Z"}))
                sig = sign_file(path, key_file)
                server.files["/lunexeconom/update.json"] = path.read_bytes()
                server.files["/lunexeconom/update.json.sig"] = sig.read_bytes()
                content = temp / "content.json"
                content.write_bytes(canonical_json(pack_info))
                content_sig = sign_file(content, key_file)
                server.files["/lunexeconom/content.json"] = content.read_bytes().replace(b"core_start", b"bad_start")
                server.files["/lunexeconom/content.json.sig"] = content_sig.read_bytes()
                server.files["/lunexeconom/download/lunex.apk"] = payload
                server.files["/lunexeconom/packs/core_start-1.0.0.pck"] = pack.read_bytes()
                env = dict(os.environ)
                env["XDG_DATA_HOME"] = str(temp / "xdgdata")
                env["XDG_CONFIG_HOME"] = str(temp / "xdgconfig")
                done = subprocess.run(
                    [GODOT, "--headless", "--path", str(ROOT / "client"),
                     "-s", "tests/network_smoke.gd", "--",
                     base, str(pub_file), str(cert_file),
                     hashlib.sha256(payload).hexdigest(), str(len(payload)),
                     sha256(pack), str(pack.stat().st_size)],
                    env=env, capture_output=True, text=True, timeout=65)
                self.assertEqual(done.returncode, 0, done.stdout + "\n" + done.stderr)
                self.assertIn("HTTPS fake-server smoke OK", done.stdout)
                self.assertIn(6, server.range_starts)
                self.assertGreaterEqual(server.range_starts.count(6), 2,
                                        "Expected an interrupted Range request to be retried")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
