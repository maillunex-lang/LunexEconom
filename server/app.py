"""Development-only authoritative HTTP foundation. No financial mutations yet."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
import json
import os
import threading
import uuid

WORLD_ID = "bashkiria-main"
MONTH_SECONDS = 86400
_lock = threading.Lock()
_sessions = {}

def response(path):
    if path == "/health":
        return 200, {"ok": True, "service": "lunexeconom-foundation", "version": "0.1.0"}
    if path == "/world":
        return 200, {"world_id": WORLD_ID, "month_seconds": MONTH_SECONDS, "regions_planned": 20, "regions_active": 0}
    return 404, {"error": "not_found"}

def join(nickname):
    if not isinstance(nickname, str) or not (2 <= len(nickname.strip()) <= 32):
        return 400, {"error": "invalid_nickname"}
    if any(ord(c) < 32 for c in nickname):
        return 400, {"error": "invalid_nickname"}
    with _lock:
        sid = uuid.uuid4().hex
        _sessions[sid] = nickname.strip()
    return 201, {"session_id": sid, "world_id": WORLD_ID, "nickname": nickname.strip()}

class Handler(BaseHTTPRequestHandler):
    def _send(self, status, data):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        status, data = response(urlsplit(self.path).path)
        self._send(status, data)

    def do_POST(self):
        if urlsplit(self.path).path != "/sessions":
            return self._send(404, {"error": "not_found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024:
                return self._send(400, {"error": "invalid_body"})
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                return self._send(400, {"error": "invalid_body"})
            status, payload = join(data.get("nickname"))
            return self._send(status, payload)
        except (ValueError, UnicodeError, json.JSONDecodeError):
            return self._send(400, {"error": "invalid_body"})

def main():
    # Bind loopback by default. No public port without a separate deployment decision.
    host = os.environ.get("LUNEX_BIND", "127.0.0.1")
    port = int(os.environ.get("LUNEX_PORT", "18761"))
    ThreadingHTTPServer((host, port), Handler).serve_forever()

if __name__ == "__main__":
    main()