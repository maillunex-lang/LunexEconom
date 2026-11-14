"""Administration API on a disposable PostgreSQL 16 database named lunex_ci. Never point this at production."""
import os
import unittest
import uuid

ENABLED = os.environ.get("LUNEX_DB_ENGINE") == "postgres" and os.environ.get("LUNEX_PG_DB") == "lunex_ci"

if ENABLED:
    import admin_api
    import auth
    import postgres_db
    import postgres_world


@unittest.skipUnless(ENABLED, "requires isolated lunex_ci PostgreSQL database")
class PostgresAdminTests(unittest.TestCase):
    def setUp(self):
        postgres_db.init()
        with postgres_db.connect() as db:
            # Other PostgreSQL test modules leave rows behind (the CI runs them in one database, in a fixed order): start from nothing.
            names = [r[0] for r in db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()]
            db.execute("TRUNCATE TABLE " + ",".join(sorted(n for n in names if n != "schema_migrations")) + " RESTART IDENTITY CASCADE")
        self.name = "adm" + uuid.uuid4().hex[:8]
        code, data = auth.register({"username": self.name, "email": self.name + "@example.test", "password": "safe-password-1"}, "pg-" + self.name)
        self.assertIn(code, (200, 201), data)
        self.token = data.get("token") or data.get("access_token")
        self.ctx = {"actor": "pg-test", "ip": "198.51.100.1"}

    def admin(self, method, path, args=None, payload=None):
        return postgres_world.admin_request(method, path, args or {}, payload or {}, self.ctx)

    def test_overview_and_clean_ledger(self):
        status, data = self.admin("GET", "/admin/overview")
        self.assertEqual(status, 200, data)
        self.assertEqual(data["ledger"]["unbalanced_transactions"], 0)
        self.assertEqual(data["ledger"]["wallet_sum"], 0)
        self.assertEqual(data["accounts"]["accounts"], 1)

    def test_ban_blocks_session_and_login_then_unban(self):
        self.assertEqual(auth.profile(self.token)[0], 200)
        status, data = self.admin("POST", "/admin/ban", payload={"username": self.name, "reason": "тест PG"})
        self.assertEqual(status, 200, data)
        self.assertEqual(auth.profile(self.token)[0], 401)           # its sessions were deleted
        code, result = auth.login({"identifier": self.name, "password": "safe-password-1"}, "pg-login")
        self.assertEqual((code, result["error"]), (403, "banned"))
        self.assertEqual(self.admin("POST", "/admin/unban", payload={"username": self.name})[0], 200)
        self.assertEqual(auth.login({"identifier": self.name, "password": "safe-password-1"}, "pg-login2")[0], 200)

    def test_players_have_no_credentials_in_the_answer(self):
        status, data = self.admin("GET", "/admin/players", {"q": self.name[:5]})
        self.assertEqual(status, 200)
        self.assertEqual([p["username"] for p in data["players"]], [self.name])
        self.assertNotIn("@example.test", repr(data))

    def test_reports_announcement_and_audit(self):
        with postgres_db.connect() as db:
            db.execute("INSERT INTO soc_reports(id,reporter,target,reason,created) VALUES('r1','a','b','спам',1800000000)")
        self.assertEqual(self.admin("GET", "/admin/reports")[1]["reports"][0]["id"], "r1")
        self.assertEqual(self.admin("POST", "/admin/report/resolve", payload={"id": "r1", "status": "dismissed", "note": "ок"})[0], 200)
        self.assertEqual(self.admin("GET", "/admin/reports")[1]["reports"], [])
        self.assertEqual(self.admin("POST", "/admin/announce", payload={"text": "Обновление"})[0], 200)
        self.assertEqual(postgres_world.announcement_state()[1]["text"], "Обновление")
        self.assertEqual(self.admin("POST", "/admin/announce", payload={"text": "<b>"})[0], 400)
        actions = [a["action"] for a in self.admin("GET", "/admin/audit")[1]["audit"]]
        self.assertEqual(sorted(actions), ["announcement_set", "report_dismissed"])

    def test_moderation_leaves_the_ledger_untouched(self):
        def snapshot():
            with postgres_db.connect() as db:
                return [db.execute("SELECT COUNT(*) FROM " + t).fetchone()[0] for t in ("ledger_tx", "ledger_entries", "wallets", "buildings")]
        before = snapshot()
        self.admin("POST", "/admin/ban", payload={"username": self.name, "reason": "тест"})
        self.admin("POST", "/admin/unban", payload={"username": self.name})
        self.admin("POST", "/admin/announce", payload={"text": "x"})
        self.assertEqual(before, snapshot())


if __name__ == "__main__":
    unittest.main()
