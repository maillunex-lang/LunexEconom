"""Calls to the game server's administration API (server/admin_api.py). The upstream is fixed by the operator, never by a request."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

MAX_RESPONSE = 1024 * 1024
TIMEOUT = 8
GET_PATHS = ("/admin/overview", "/admin/players", "/admin/player", "/admin/reports", "/admin/audit", "/admin/cities", "/admin/config", "/admin/revisions", "/admin/online", "/admin/online/players", "/admin/status", "/admin/config/candidate")
POST_PATHS = ("/admin/ban", "/admin/unban", "/admin/report/resolve", "/admin/announce", "/admin/cities/seed", "/admin/config/set", "/admin/config/rollback", "/admin/config/client", "/admin/config/sign")


class GameAdminError(Exception):
    def __init__(self, status, payload):
        super().__init__(str(status))
        self.status, self.payload = status, payload


class GameClient:
    def __init__(self, base=None, token=None):
        self.base = (base or os.environ.get("LUNEX_GAME_ADMIN_UPSTREAM", "http://127.0.0.1:18767")).rstrip("/")
        if urllib.parse.urlsplit(self.base).scheme not in ("http", "https"):
            raise ValueError("game admin upstream must be http(s)")
        self.token = token if token is not None else os.environ.get("LUNEX_GAME_ADMIN_TOKEN", "")

    @property
    def configured(self):
        return len(self.token) >= 32

    def request(self, method, path, query=None, payload=None, actor="studio", ip="-"):
        if not self.configured:
            raise GameAdminError(503, {"error": "game_admin_not_configured"})
        if (method == "GET" and path not in GET_PATHS) or (method == "POST" and path not in POST_PATHS):
            raise GameAdminError(404, {"error": "not_found"})
        url = self.base + path + ("?" + urllib.parse.urlencode(query) if query else "")
        data = None if method == "GET" else json.dumps(payload or {}).encode("utf-8")
        headers = {"Authorization": "Bearer " + self.token, "X-Admin-Actor": str(actor)[:32], "X-Admin-Client": str(ip)[:64]}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                body = response.read(MAX_RESPONSE + 1)
                status = response.status
        except urllib.error.HTTPError as error:
            body, status = error.read(MAX_RESPONSE + 1), error.code
        except (urllib.error.URLError, TimeoutError, OSError):
            raise GameAdminError(503, {"error": "game_server_unavailable"})
        if len(body) > MAX_RESPONSE:
            raise GameAdminError(502, {"error": "response_too_large"})
        try:
            result = json.loads(body)
        except ValueError:
            raise GameAdminError(502, {"error": "bad_upstream_response"})
        if status >= 400:
            raise GameAdminError(status, result)
        return result
