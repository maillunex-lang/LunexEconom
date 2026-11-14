"""Game administration API on disposable SQLite databases: access control, monitoring, moderation, announcements, audit."""
import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

import admin_api
import auth
import economy
import game_server

TOKEN = "t" * 40


class AdminBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(game_server, "DB", os.path.join(self.tmp.name, "world.sqlite3")),
            mock.patch.object(auth, "DB_PATH", os.path.join(self.tmp.name, "accounts.sqlite3")),
            mock.patch.dict(os.environ, {admin_api.TOKEN_ENV: TOKEN}),
        ]
        for patch in self.patches:
            patch.start()
        admin_api.clear_failures()
        with game_server.connect() as db:
            db.execute("INSERT INTO world_clock VALUES(1,1800000000,86400,0)")
        self.sessions = {}
        for name in ("alice", "bobby"):
            code, data = auth.register({"username": name, "email": name + "@example.test", "password": "safe-password-1"}, "c-" + name)
            self.assertIn(code, (200, 201), data)
            self.sessions[name] = data["token"] if "token" in data else data.get("access_token")
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), game_server.Handler)
        self.port = self.http.server_address[1]
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()

    def call(self, method, path, body=None, headers=None, token=TOKEN):
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
        try:
            return response.status, json.loads(data)
        except ValueError:
            return response.status, data

    def snapshot(self):
        with game_server.connect() as db:
            return {t: db.execute("SELECT * FROM " + t + " ORDER BY 1").fetchall() for t in ("wallets", "ledger_tx", "ledger_entries", "buildings", "building_ops")}


class AccessTests(AdminBase):
    def test_valid_token_on_loopback_is_accepted(self):
        status, data = self.call("GET", "/admin/overview")
        self.assertEqual(status, 200, data)
        self.assertTrue(data["ok"])

    def test_wrong_or_missing_token_is_unauthorized(self):
        self.assertEqual(self.call("GET", "/admin/overview", token="x" * 40)[0], 401)
        self.assertEqual(self.call("GET", "/admin/overview", token=None)[0], 401)

    def test_request_through_the_proxy_is_invisible_even_with_the_right_token(self):
        for header in ("X-Real-IP", "X-Forwarded-For", "Forwarded"):
            status, _ = self.call("GET", "/admin/overview", headers={header: "203.0.113.5"})
            self.assertEqual(status, 404, header)
            status, _ = self.call("POST", "/admin/announce", {"text": "x"}, headers={header: "203.0.113.5"})
            self.assertEqual(status, 404, header)

    def test_disabled_without_a_long_token(self):
        with mock.patch.dict(os.environ, {admin_api.TOKEN_ENV: "short"}):
            self.assertEqual(self.call("GET", "/admin/overview", token="short")[0], 404)
        with mock.patch.dict(os.environ, {admin_api.TOKEN_ENV: ""}):
            self.assertEqual(self.call("GET", "/admin/overview", token="")[0], 404)

    def test_repeated_failures_are_throttled(self):
        for _ in range(admin_api.FAIL_LIMIT):
            self.assertEqual(self.call("GET", "/admin/overview", token="bad" * 15)[0], 401)
        self.assertEqual(self.call("GET", "/admin/overview", token="bad" * 15)[0], 429)
        self.assertEqual(self.call("GET", "/admin/overview")[0], 429)       # even the right token waits out the window

    def test_non_ascii_authorization_does_not_crash(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest("GET", "/admin/overview")
        conn.putheader("Authorization", "Bearer éè".encode("latin-1").decode("latin-1"))
        conn.endheaders()
        self.assertEqual(conn.getresponse().status, 401)
        conn.close()

    def test_unknown_admin_path_and_bad_body(self):
        self.assertEqual(self.call("GET", "/admin/nope")[0], 404)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/admin/announce", body=b"not json", headers={"Authorization": "Bearer " + TOKEN, "Content-Length": "8"})
        self.assertEqual(conn.getresponse().status, 400)
        conn.close()

    def test_player_tokens_do_not_open_the_admin_api(self):
        self.assertEqual(self.call("GET", "/admin/overview", token=self.sessions["alice"])[0], 401)


class MonitoringTests(AdminBase):
    def test_overview_reports_a_clean_ledger(self):
        status, data = self.call("GET", "/admin/overview")
        self.assertEqual(data["ledger"]["unbalanced_transactions"], 0)
        self.assertEqual(data["ledger"]["wallet_sum"], 0)
        self.assertEqual(data["warnings"], [])
        self.assertEqual(data["accounts"]["accounts"], 2)
        self.assertIn("system:treasury", data["system_accounts"])

    def test_overview_detects_a_broken_ledger(self):
        with game_server.connect() as db:
            db.execute("INSERT INTO wallets VALUES('player:alice',500)")
            db.execute("INSERT INTO ledger_tx VALUES('t1','x','broken',1800000000)")
            db.execute("INSERT INTO ledger_entries VALUES('t1','player:alice',500)")
        _, data = self.call("GET", "/admin/overview")
        self.assertEqual(data["ledger"]["unbalanced_transactions"], 1)
        self.assertEqual(len(data["warnings"]), 2)

    def test_players_list_has_no_email_or_password_material(self):
        status, data = self.call("GET", "/admin/players")
        self.assertEqual(status, 200)
        names = {p["username"] for p in data["players"]}
        self.assertEqual(names, {"alice", "bobby"})
        text = json.dumps(data)
        for secret in ("@example.test", "password", "salt", "hash"):
            self.assertNotIn(secret, text)
        status, data = self.call("GET", "/admin/players?q=ali")
        self.assertEqual([p["username"] for p in data["players"]], ["alice"])

    def test_player_card_and_validation(self):
        with game_server.connect() as db:
            db.execute("INSERT INTO wallets VALUES('player:alice',123)")
        status, data = self.call("GET", "/admin/player?name=alice")
        self.assertEqual((status, data["balance"]), (200, 123))
        self.assertEqual(self.call("GET", "/admin/player?name=../etc")[0], 400)

    def test_reading_changes_nothing(self):
        before = self.snapshot()
        for path in ("/admin/overview", "/admin/players", "/admin/player?name=alice", "/admin/reports", "/admin/audit"):
            self.call("GET", path)
        self.assertEqual(before, self.snapshot())


class ModerationTests(AdminBase):
    def login(self, name):
        return auth.login({"identifier": name, "password": "safe-password-1"}, "c-login-" + name)

    def test_ban_blocks_login_and_existing_sessions_then_unban_restores(self):
        self.assertEqual(auth.profile(self.sessions["alice"])[0], 200)
        status, data = self.call("POST", "/admin/ban", {"username": "alice", "reason": "спам в чате"})
        self.assertEqual(status, 200, data)
        self.assertNotEqual(auth.profile(self.sessions["alice"])[0], 200)
        code, result = self.login("alice")
        self.assertEqual((code, result["error"]), (403, "banned"))
        self.assertEqual(self.login("bobby")[0], 200)
        status, data = self.call("POST", "/admin/unban", {"username": "alice"})
        self.assertEqual(status, 200)
        self.assertEqual(self.login("alice")[0], 200)

    def test_banned_player_cannot_use_game_endpoints(self):
        self.call("POST", "/admin/ban", {"username": "bobby", "reason": "тест"})
        status, _ = self.call("GET", "/wallet", token=self.sessions["bobby"])
        self.assertEqual(status, 401)

    def test_temporary_ban_expires(self):
        self.call("POST", "/admin/ban", {"username": "alice", "reason": "тест", "days": 1})
        self.assertEqual(self.login("alice")[0], 403)
        with mock.patch("auth.time.time", return_value=__import__("time").time() + 2 * 86400):
            self.assertEqual(self.login("alice")[0], 200)

    def test_invalid_ban_requests(self):
        self.assertEqual(self.call("POST", "/admin/ban", {"username": "ghost", "reason": "тест"})[0], 404)
        self.assertEqual(self.call("POST", "/admin/ban", {"username": "alice", "reason": ""})[0], 400)
        self.assertEqual(self.call("POST", "/admin/ban", {"username": "alice", "reason": "x", "days": -5})[0], 400)
        self.assertEqual(self.call("POST", "/admin/ban", {"username": "alice", "reason": "x" * 300})[0], 400)
        self.assertEqual(self.call("POST", "/admin/unban", {"username": "alice"})[0], 404)

    def test_ban_flags_show_up_in_the_player_lists(self):
        self.call("POST", "/admin/ban", {"username": "alice", "reason": "тест"})
        _, data = self.call("GET", "/admin/players")
        flags = {p["username"]: p["banned"] for p in data["players"]}
        self.assertEqual(flags, {"alice": True, "bobby": False})
        _, overview = self.call("GET", "/admin/overview")
        self.assertEqual(overview["accounts"]["active_bans"], 1)

    def test_reports_queue_and_resolution(self):
        with game_server.connect() as db:
            db.execute("INSERT INTO soc_reports VALUES('r1','alice','bobby','оскорбления',1800000100)")
            db.execute("INSERT INTO soc_reports VALUES('r2','bobby','alice','спам',1800000200)")
        _, data = self.call("GET", "/admin/reports")
        self.assertEqual([r["id"] for r in data["reports"]], ["r2", "r1"])
        self.assertEqual(self.call("POST", "/admin/report/resolve", {"id": "r2", "status": "actioned", "note": "бан на сутки"})[0], 200)
        _, data = self.call("GET", "/admin/reports")
        self.assertEqual([r["id"] for r in data["reports"]], ["r1"])
        _, data = self.call("GET", "/admin/reports?status=all")
        self.assertEqual({r["id"]: r["status"] for r in data["reports"]}, {"r1": "open", "r2": "actioned"})
        self.assertEqual(self.call("POST", "/admin/report/resolve", {"id": "zz", "status": "dismissed", "note": ""})[0], 404)
        self.assertEqual(self.call("POST", "/admin/report/resolve", {"id": "r1", "status": "deleted", "note": ""})[0], 400)
        self.assertEqual(self.call("POST", "/admin/report/resolve", {"id": "r1", "status": "dismissed", "note": "<b>"})[0], 400)

    def test_player_card_shows_reports_and_ban(self):
        with game_server.connect() as db:
            db.execute("INSERT INTO soc_reports VALUES('r1','bobby','alice','спам',1800000100)")
        self.call("POST", "/admin/ban", {"username": "alice", "reason": "спам"})
        _, data = self.call("GET", "/admin/player?name=alice")
        self.assertEqual(data["reports_against"], 1)
        self.assertEqual(data["ban"]["reason"], "спам")

    def test_moderation_never_touches_money_or_buildings(self):
        with game_server.connect() as db:
            db.execute("INSERT INTO soc_reports VALUES('r1','bobby','alice','спам',1800000100)")
        before = self.snapshot()
        self.call("POST", "/admin/ban", {"username": "alice", "reason": "тест"})
        self.call("POST", "/admin/unban", {"username": "alice"})
        self.call("POST", "/admin/report/resolve", {"id": "r1", "status": "dismissed", "note": "ок"})
        self.call("POST", "/admin/announce", {"text": "Работы на сервере"})
        self.assertEqual(before, self.snapshot())


class AnnouncementAndAuditTests(AdminBase):
    def test_announcement_is_public_and_clearable(self):
        status, data = self.call("GET", "/announcement", token=None)
        self.assertEqual((status, data["text"]), (200, ""))
        self.assertEqual(self.call("POST", "/admin/announce", {"text": "Завтра обновление"})[0], 200)
        _, data = self.call("GET", "/announcement", token=None)
        self.assertEqual(data["text"], "Завтра обновление")
        self.call("POST", "/admin/announce", {"text": ""})
        _, data = self.call("GET", "/announcement", token=None)
        self.assertEqual(data["text"], "")

    def test_announcement_validation(self):
        for text in ("<script>", "x" * 201, "line\nbreak"):
            self.assertEqual(self.call("POST", "/admin/announce", {"text": text})[0], 400, text)

    def test_every_change_is_audited_with_actor_and_ip(self):
        headers = {"X-Admin-Actor": "moderator1", "X-Admin-Client": "198.51.100.7"}
        self.call("POST", "/admin/announce", {"text": "привет"}, headers=headers)
        self.call("POST", "/admin/ban", {"username": "alice", "reason": "тест"}, headers=headers)
        _, data = self.call("GET", "/admin/audit")
        actions = [(a["action"], a["actor"], a["ip"]) for a in data["audit"]]
        self.assertIn(("ban", "moderator1", "198.51.100.7"), actions)
        self.assertIn(("announcement_set", "moderator1", "198.51.100.7"), actions)

    def test_rejected_changes_are_not_audited(self):
        self.call("POST", "/admin/announce", {"text": "<b>"})
        _, data = self.call("GET", "/admin/audit")
        self.assertEqual(data["audit"], [])


if __name__ == "__main__":
    unittest.main()
