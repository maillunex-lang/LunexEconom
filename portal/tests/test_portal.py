import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from portal import auth, bootstrap, db
from portal.app import create_app
from tools import work_plan as wp

ROOT = Path(__file__).resolve().parents[2]
PW = "correct-horse-battery"


def call(app, method, path, body=None, cookie="", csrf="", ip="10.0.0.1"):
    raw = json.dumps(body).encode() if body is not None else b""
    res = {}
    def start(status, headers):
        res["status"] = int(status.split()[0]); res["headers"] = dict(headers); res["list"] = headers
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw),
           "REMOTE_ADDR": ip, "HTTP_COOKIE": cookie, "HTTP_X_CSRF_TOKEN": csrf}
    out = b"".join(app(env, start))
    res["body"] = out
    try:
        res["json"] = json.loads(out.decode())
    except Exception:
        res["json"] = None
    return res


class Portal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "p.sqlite")
        conn = db.connect(self.path)
        auth.set_password(conn, "owner", PW)
        conn.close()
        self.app = create_app(self.path, base="/createportal", secure_cookie=True)

    def tearDown(self):
        self.app.close(); self.tmp.cleanup()

    def login(self, ip="10.0.0.1"):
        r = call(self.app, "POST", "/createportal/api/login", {"username": "owner", "password": PW}, ip=ip)
        self.assertEqual(r["status"], 200, r)
        cookie = r["headers"]["Set-Cookie"].split(";")[0]
        me = call(self.app, "GET", "/createportal/api/me", cookie=cookie)
        return cookie, me["json"]["csrf"]

    def test_requires_login(self):
        for path in ("/api/me", "/api/projects", "/api/protocol"):
            self.assertEqual(call(self.app, "GET", "/createportal" + path)["status"], 401)

    def test_login_cookie_flags_and_wrong_password(self):
        r = call(self.app, "POST", "/createportal/api/login", {"username": "owner", "password": PW})
        c = r["headers"]["Set-Cookie"]
        for flag in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/createportal"):
            self.assertIn(flag, c)
        self.assertEqual(call(self.app, "POST", "/createportal/api/login", {"username": "owner", "password": "bad"}, ip="9.9.9.9")["status"], 401)
        self.assertEqual(call(self.app, "POST", "/createportal/api/login", {"username": "nobody", "password": "bad"}, ip="9.9.9.8")["status"], 401)

    def test_rate_limit(self):
        for _ in range(auth.ATTEMPT_LIMIT):
            call(self.app, "POST", "/createportal/api/login", {"username": "owner", "password": "bad"}, ip="7.7.7.7")
        r = call(self.app, "POST", "/createportal/api/login", {"username": "owner", "password": PW}, ip="7.7.7.7")
        self.assertEqual(r["status"], 429)

    def test_csrf_required_on_post(self):
        cookie, csrf = self.login()
        body = {"slug": "demo-project", "name": "Demo"}
        self.assertEqual(call(self.app, "POST", "/createportal/api/projects", body, cookie=cookie)["status"], 403)
        self.assertEqual(call(self.app, "POST", "/createportal/api/projects", body, cookie=cookie, csrf="wrong")["status"], 403)
        self.assertEqual(call(self.app, "POST", "/createportal/api/projects", body, cookie=cookie, csrf=csrf)["status"], 201)

    def test_security_headers_and_html_nonce(self):
        r = call(self.app, "GET", "/createportal/")
        h = r["headers"]
        self.assertIn("nonce-", h["Content-Security-Policy"])
        self.assertEqual(h["X-Frame-Options"], "DENY")
        self.assertIn(b"CreatePortal", r["body"])
        self.assertNotIn(b"__NONCE__", r["body"])
        nonce = h["Content-Security-Policy"].split("nonce-")[1].split("'")[0]
        self.assertIn(nonce.encode(), r["body"])

    def create_project(self, cookie, csrf, slug="demo-project"):
        r = call(self.app, "POST", "/createportal/api/projects", {"slug": slug, "name": "Demo", "repo": "owner/demo", "description": "d"}, cookie=cookie, csrf=csrf)
        self.assertEqual(r["status"], 201, r)
        return r

    def test_project_validation_and_duplicates(self):
        cookie, csrf = self.login()
        self.create_project(cookie, csrf)
        self.assertEqual(call(self.app, "POST", "/createportal/api/projects", {"slug": "demo-project", "name": "x"}, cookie=cookie, csrf=csrf)["status"], 409)
        for bad in ({"slug": "A", "name": "x"}, {"slug": "ok-slug", "name": ""}, {"slug": "ok-slug", "name": "x", "repo": "not a repo"}, {"slug": "../etc", "name": "x"}):
            self.assertEqual(call(self.app, "POST", "/createportal/api/projects", bad, cookie=cookie, csrf=csrf)["status"], 400, bad)

    def test_bootstrap_prompt_and_zip(self):
        cookie, csrf = self.login()
        r = self.create_project(cookie, csrf)
        self.assertIn("work_plan.json", r["json"]["prompt"])
        z = call(self.app, "GET", "/createportal/api/projects/demo-project/bootstrap.zip", cookie=cookie)
        self.assertEqual(z["headers"]["Content-Type"], "application/zip")
        names = zipfile.ZipFile(io.BytesIO(z["body"])).namelist()
        for need in ("docs/work_plan.json", "docs/WORK_PLAN.md", "docs/AI_RULES.md", "docs/PORTAL_PROTOCOL.md", "tools/work_plan.py", "README.md"):
            self.assertIn(need, names)
        self.assertFalse(any(n.startswith("/") or ".." in n for n in names))

    def test_starter_plan_valid_and_prompts_generic(self):
        plan = bootstrap.STARTER_PLAN
        self.assertEqual(wp.validate(plan), [])
        text = wp.prompt(plan, "A1")
        self.assertNotIn("Godot", text)
        self.assertNotIn("PostgreSQL", text)

    def test_plan_import_and_status_flow(self):
        cookie, csrf = self.login()
        self.create_project(cookie, csrf)
        base = "/createportal/api/projects/demo-project"
        self.assertEqual(call(self.app, "POST", base + "/plan", {"plan": {"packages": []}}, cookie=cookie, csrf=csrf)["status"], 400)
        bad = json.loads(json.dumps(bootstrap.STARTER_PLAN)); bad["packages"][0]["depends_on"] = ["NOPE"]
        self.assertEqual(call(self.app, "POST", base + "/plan", {"plan": bad}, cookie=cookie, csrf=csrf)["status"], 422)
        plan = json.loads(json.dumps(bootstrap.STARTER_PLAN))
        plan["packages"].append({"id": "A2", "title": "Второй", "lane": "A", "step": 2, "depends_on": ["A1"], "gdd": ["01"], "goal": "g", "done_when": ["x"], "zone_extra": [], "status": "planned", "size": "S"})
        self.assertEqual(call(self.app, "POST", base + "/plan", {"plan": plan}, cookie=cookie, csrf=csrf)["status"], 200)
        # зависимость не принята, выдать нельзя
        self.assertEqual(call(self.app, "POST", base + "/status", {"id": "A2", "status": "issued"}, cookie=cookie, csrf=csrf)["status"], 409)
        for st in ("issued", "submitted"):
            self.assertEqual(call(self.app, "POST", base + "/status", {"id": "A1", "status": st}, cookie=cookie, csrf=csrf)["status"], 200)
        r = call(self.app, "POST", base + "/status", {"id": "A1", "status": "accepted", "merged": True, "sha": "abc1234", "note": "слито"}, cookie=cookie, csrf=csrf)
        self.assertEqual(r["status"], 200)
        self.assertEqual(call(self.app, "POST", base + "/status", {"id": "A2", "status": "issued"}, cookie=cookie, csrf=csrf)["status"], 200)
        d = call(self.app, "GET", base, cookie=cookie)["json"]
        self.assertEqual(d["state"]["A1"]["status"], "accepted")
        self.assertEqual(d["state"]["A1"]["sha"], "abc1234")
        self.assertEqual(d["state"]["A1"]["merged"], 1)
        self.assertTrue(d["packages"][0]["prompt"])
        self.assertEqual(call(self.app, "POST", base + "/status", {"id": "NOPE", "status": "issued"}, cookie=cookie, csrf=csrf)["status"], 400)
        self.assertEqual(call(self.app, "POST", base + "/status", {"id": "A1", "status": "hacked"}, cookie=cookie, csrf=csrf)["status"], 400)

    def test_sync_uses_injected_fetch_and_validates(self):
        calls = []
        def fake(url, token):
            calls.append(url); return json.dumps(bootstrap.STARTER_PLAN)
        app = create_app(self.path, base="/createportal", fetch=fake)
        r = call(app, "POST", "/createportal/api/login", {"username": "owner", "password": PW}, ip="1.1.1.1")
        cookie = r["headers"]["Set-Cookie"].split(";")[0]
        csrf = call(app, "GET", "/createportal/api/me", cookie=cookie)["json"]["csrf"]
        call(app, "POST", "/createportal/api/projects", {"slug": "demo-project", "name": "Demo", "repo": "owner/demo"}, cookie=cookie, csrf=csrf)
        s = call(app, "POST", "/createportal/api/projects/demo-project/sync", {}, cookie=cookie, csrf=csrf)
        self.assertEqual(s["status"], 200, s)
        self.assertIn("owner/demo", calls[0])
        app.close()

    def test_oversize_body_rejected(self):
        cookie, csrf = self.login()
        env_big = call(self.app, "POST", "/createportal/api/projects", {"slug": "x" * 5, "name": "y" * 2_000_000}, cookie=cookie, csrf=csrf)
        self.assertIn(env_big["status"], (400, 413))

    def test_protocol_matches_template(self):
        cookie, _ = self.login()
        md = call(self.app, "GET", "/createportal/api/protocol", cookie=cookie)["json"]["markdown"]
        self.assertEqual(md, (ROOT / "portal/templates/PORTAL_PROTOCOL.md").read_text(encoding="utf-8"))
        self.assertIn("work_plan.json", md)

    def test_template_work_plan_not_drifted(self):
        self.assertEqual((ROOT / "portal/templates/work_plan.py").read_text(encoding="utf-8"), (ROOT / "tools/work_plan.py").read_text(encoding="utf-8"))

    def test_password_policy_and_hash(self):
        conn = db.connect(self.path)
        with self.assertRaises(ValueError):
            auth.set_password(conn, "owner", "short")
        h = auth.hash_password("x" * 20)
        self.assertTrue(auth.verify_password("x" * 20, h))
        self.assertFalse(auth.verify_password("y" * 20, h))
        self.assertNotIn("x" * 20, h)
        conn.close()

    def test_logout_invalidates_session(self):
        cookie, csrf = self.login()
        call(self.app, "POST", "/createportal/api/logout", {}, cookie=cookie, csrf=csrf)
        self.assertEqual(call(self.app, "GET", "/createportal/api/me", cookie=cookie)["status"], 401)


if __name__ == "__main__":
    unittest.main()
