"""WSGI-приложение портала CreatePortal. Префикс (например /createportal) срезается; JSON API под /api, одна HTML-страница."""
from __future__ import annotations

import json
import os
import re
import secrets
import time
import urllib.request
from http.cookies import SimpleCookie
from pathlib import Path

from . import auth, bootstrap, db
from tools import work_plan as wp  # общие проверка плана и генерация промптов

MAX_BODY = 1_000_000
STATUSES = ("planned", "issued", "submitted", "accepted")
COOKIE = "portal_session"
STATIC = Path(__file__).with_name("static")


def _prompted(plan):
    return [dict(p, prompt=wp.prompt(plan, p["id"])) for p in plan["packages"]]


def create_app(db_path, base="", secure_cookie=True, fetch=None, github_token_file=None, security_v2=False):
    conn = db.connect(db_path)
    base = base.rstrip("/")

    def respond(start, status, body, headers=None, nonce=None):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        h = [("Content-Length", str(len(data))), ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"),
             ("X-Frame-Options", "DENY"),
             ("Content-Security-Policy", "default-src 'none'; connect-src 'self'; img-src 'self' data:; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; script-src 'nonce-%s'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; manifest-src 'self'; worker-src 'self'" % (nonce or "x"))]
        if not any(k == "Cache-Control" for k, _ in (headers or [])):
            h.append(("Cache-Control", "no-store"))
        if not any(k == "Content-Type" for k, _ in (headers or [])):
            h.append(("Content-Type", "application/json; charset=utf-8"))
        start(status, h + (headers or []))
        return [data]

    def read_body(environ):
        try:
            n = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            return None
        if n < 0 or n > MAX_BODY:
            return None
        raw = environ["wsgi.input"].read(n) if n else b""
        try:
            data = json.loads(raw.decode() or "{}")
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def project_row(slug):
        return conn.execute("SELECT * FROM projects WHERE slug=?", (slug,)).fetchone()

    def states(slug):
        return {r["pkg_id"]: {k: r[k] for k in ("status", "issued_at", "submitted_at", "accepted_at", "merged", "sha", "note")}
                for r in conn.execute("SELECT * FROM task_state WHERE project_slug=?", (slug,))}

    def start_list(row):
        done = {r["prompt_id"]: r["done"] for r in conn.execute("SELECT prompt_id,done FROM start_state WHERE project_slug=?", (row["slug"],))}
        return [dict(x, done=bool(done.get(x["id"], 0))) for x in bootstrap.start_prompts(row["name"], row["repo"], row["description"])]

    def ideas_list(slug):
        return [{"id": r["id"], "text": r["text"], "created": r["created"]} for r in conn.execute("SELECT * FROM ideas WHERE project_slug=? AND done=0 ORDER BY id DESC LIMIT 200", (slug,))]

    def summary(row):
        plan = json.loads(row["plan_json"]) if row["plan_json"] else None
        st = states(row["slug"])
        total = len(plan["packages"]) if plan else 0
        done = sum(1 for v in st.values() if v["status"] == "accepted")
        return {"slug": row["slug"], "name": row["name"], "repo": row["repo"], "description": row["description"],
                "total": total, "accepted": done, "has_plan": bool(plan)}

    def fetch_plan(repo):
        token = ""
        if github_token_file and Path(github_token_file).is_file():
            token = Path(github_token_file).read_text().strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo or ""):
            raise ValueError("repo_invalid")
        url = f"https://api.github.com/repos/{repo}/contents/docs/work_plan.json"
        if fetch:
            return fetch(url, token)
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github.raw+json", "User-Agent": "createportal",
                                                   **({"Authorization": "Bearer " + token} if token else {})})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read(MAX_BODY).decode()

    def app(environ, start):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/")
        if base and path.startswith(base):
            path = path[len(base):] or "/"
        ip = (environ.get("REMOTE_ADDR") or "-")[:64]  # never trust client-supplied forwarding headers
        try:
            cookies = SimpleCookie(environ.get("HTTP_COOKIE", "")[:4096])
        except Exception:
            cookies = SimpleCookie()
        token = cookies[COOKIE].value if COOKIE in cookies else ""
        if path == "/health" and method == "GET":
            healthy = db.check_health(conn)
            return respond(start, "200 OK" if healthy else "503 Service Unavailable", {"ok": healthy})
        if method == "GET" and path in ("/", "/index.html"):
            nonce = secrets.token_urlsafe(12)
            html = (STATIC / "index.html").read_text(encoding="utf-8").replace("__NONCE__", nonce).replace("__BASE__", base)
            return respond(start, "200 OK", html.encode(), [("Content-Type", "text/html; charset=utf-8")], nonce)
        if method == "GET" and path == "/manifest.webmanifest":
            man = {"name": "CreatePortal", "short_name": "Портал", "description": "Проекты, задачи и приёмка работы исполнителей",
                   "lang": "ru", "start_url": (base or "") + "/", "scope": (base or "") + "/", "display": "standalone", "orientation": "portrait",
                   "background_color": "#DDE8DF", "theme_color": "#1F7A4D",
                   "icons": [{"src": (base or "") + "/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
                             {"src": (base or "") + "/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
                             {"src": (base or "") + "/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]}
            return respond(start, "200 OK", json.dumps(man, ensure_ascii=False).encode(), [("Content-Type", "application/manifest+json; charset=utf-8")])
        if method == "GET" and path == "/sw.js":
            js = (STATIC / "sw.js").read_text(encoding="utf-8").replace("__BASE__", base)
            return respond(start, "200 OK", js.encode(), [("Content-Type", "text/javascript; charset=utf-8"), ("Service-Worker-Allowed", (base or "") + "/")])
        m_icon = re.fullmatch(r"/icons/(icon-192\.png|icon-512\.png|icon-maskable-512\.png|icon\.svg)", path)
        if method == "GET" and m_icon:
            f = STATIC / "icons" / m_icon.group(1)
            ctype = "image/svg+xml" if f.suffix == ".svg" else "image/png"
            return respond(start, "200 OK", f.read_bytes(), [("Content-Type", ctype), ("Cache-Control", "public, max-age=86400")])
        if not path.startswith("/api/"):
            return respond(start, "404 Not Found", {"error": "not_found"})
        sess = auth.session(conn, token)
        if path == "/api/login" and method == "POST":
            body = read_body(environ)
            if body is None or set(body) != {"username", "password"} or any(type(v) is not str for v in body.values()):
                return respond(start, "400 Bad Request", {"error": "bad_request"})
            res = auth.login(conn, str(body.get("username", ""))[:80], str(body.get("password", ""))[:300], ip, hourly_limit=security_v2)
            if res == "locked":
                db.audit(conn, "login.locked", {"ip": ip})
                return respond(start, "429 Too Many Requests", {"error": "rate_limited"})
            if res == "rate":
                db.audit(conn, "login.rate_limited", {"ip": ip})
                return respond(start, "429 Too Many Requests", {"error": "rate_limited"})
            if not res:
                db.audit(conn, "login.failure", {"ip": ip})
                if security_v2 and auth.hourly_locked(conn, ip):
                    db.audit(conn, "login.locked", {"ip": ip})
                    return respond(start, "429 Too Many Requests", {"error": "rate_limited"})
                return respond(start, "401 Unauthorized", {"error": "invalid_credentials"})
            t, csrf = res
            attrs = f"{COOKIE}={t}; Path={base or '/'}; HttpOnly; SameSite=Strict; Max-Age={auth.SESSION_TTL}" + ("; Secure" if secure_cookie else "")
            db.audit(conn, "login", {"ip": ip})
            return respond(start, "200 OK", {"ok": True, "csrf": csrf}, [("Set-Cookie", attrs)])
        if not sess:
            return respond(start, "401 Unauthorized", {"error": "unauthorized"})
        if method == "POST" and environ.get("HTTP_X_CSRF_TOKEN") != sess["csrf"] and path != "/api/logout":
            return respond(start, "403 Forbidden", {"error": "csrf"})
        if path == "/api/logout" and method == "POST":
            auth.logout(conn, token)
            return respond(start, "200 OK", {"ok": True})
        if security_v2 and path == "/api/password" and method == "POST":
            body = read_body(environ)
            if body is None or set(body) != {"current_password", "new_password"} or any(type(v) is not str for v in body.values()):
                return respond(start, "400 Bad Request", {"error": "bad_request"})
            result, new_csrf = auth.change_password(conn, sess["user_id"], body["current_password"], body["new_password"], token)
            if result == "wrong":
                return respond(start, "401 Unauthorized", {"error": "invalid_credentials"})
            if result != "ok":
                return respond(start, "400 Bad Request", {"error": "invalid_password"})
            return respond(start, "200 OK", {"ok": True, "csrf": new_csrf})
        if security_v2 and path == "/api/sessions/revoke" and method == "POST":
            body = read_body(environ)
            if body is None or set(body) != {"current_password"} or type(body["current_password"]) is not str:
                return respond(start, "400 Bad Request", {"error": "bad_request"})
            if not auth.revoke_sessions(conn, sess["user_id"], body["current_password"]):
                return respond(start, "401 Unauthorized", {"error": "invalid_credentials"})
            attrs = f"{COOKIE}=; Path={base or '/'}; HttpOnly; SameSite=Strict; Max-Age=0" + ("; Secure" if secure_cookie else "")
            return respond(start, "200 OK", {"ok": True}, [("Set-Cookie", attrs)])
        if security_v2 and path == "/api/audit" and method == "GET":
            return respond(start, "200 OK", {"entries": db.recent_audit(conn)})
        if path == "/api/me" and method == "GET":
            return respond(start, "200 OK", {"user": sess["username"], "csrf": sess["csrf"]})
        if path == "/api/master-prompt" and method == "GET":
            return respond(start, "200 OK", {"markdown": (bootstrap.TPL / "MASTER_PROMPT.md").read_text(encoding="utf-8")})
        if path == "/api/skeleton.zip" and method == "GET":
            files = bootstrap.files_for("Мой проект", "", "Описание проекта.")
            return respond(start, "200 OK", bootstrap.zip_bytes(files), [("Content-Type", "application/zip"), ("Content-Disposition", 'attachment; filename="project-skeleton.zip"')])
        if path == "/api/protocol" and method == "GET":
            return respond(start, "200 OK", {"markdown": (bootstrap.TPL / "PORTAL_PROTOCOL.md").read_text(encoding="utf-8")})
        if path == "/api/projects" and method == "GET":
            return respond(start, "200 OK", {"projects": [summary(r) for r in conn.execute("SELECT * FROM projects ORDER BY created")]})
        if path == "/api/projects" and method == "POST":
            body = read_body(environ)
            if body is None:
                return respond(start, "400 Bad Request", {"error": "bad_request"})
            slug, name = str(body.get("slug", "")), str(body.get("name", "")).strip()
            repo, desc = str(body.get("repo", "")).strip()[:120], str(body.get("description", "")).strip()[:500]
            if not bootstrap.SLUG.match(slug) or not 1 <= len(name) <= 80 or (repo and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo)):
                return respond(start, "400 Bad Request", {"error": "invalid_project"})
            if project_row(slug):
                return respond(start, "409 Conflict", {"error": "exists"})
            conn.execute("INSERT INTO projects(slug,name,repo,description,created) VALUES(?,?,?,?,?)", (slug, name, repo, desc, time.time()))
            db.audit(conn, "project.create", {"slug": slug})
            return respond(start, "201 Created", {"ok": True, "slug": slug, "prompt": bootstrap.director_prompt(name, repo, desc),
                                                  "start": bootstrap.start_prompts(name, repo, desc)})
        m = re.fullmatch(r"/api/projects/([a-z][a-z0-9-]{1,38}[a-z0-9])(/[a-z.]+)?", path)
        if not m:
            return respond(start, "404 Not Found", {"error": "not_found"})
        slug, sub = m.group(1), m.group(2) or ""
        row = project_row(slug)
        if not row:
            return respond(start, "404 Not Found", {"error": "no_project"})
        if sub == "" and method == "GET":
            plan = json.loads(row["plan_json"]) if row["plan_json"] else None
            return respond(start, "200 OK", {"project": summary(row), "lanes": plan["lanes"] if plan else {}, "packages": _prompted(plan) if plan else [],
                                             "state": states(slug), "plan_updated": row["plan_updated"],
                                             "start": start_list(row), "ideas": ideas_list(slug)})
        if sub == "/bootstrap" and method == "GET":
            files = bootstrap.files_for(row["name"], row["repo"], row["description"])
            return respond(start, "200 OK", {"prompt": bootstrap.director_prompt(row["name"], row["repo"], row["description"]), "files": sorted(files),
                                             "start": bootstrap.start_prompts(row["name"], row["repo"], row["description"])})
        if sub == "/bootstrap.zip" and method == "GET":
            files = bootstrap.files_for(row["name"], row["repo"], row["description"])
            return respond(start, "200 OK", bootstrap.zip_bytes(files), [("Content-Type", "application/zip"), ("Content-Disposition", f'attachment; filename="{slug}-skeleton.zip"')])
        if sub == "/start" and method == "POST":
            body = read_body(environ)
            ids = {x["id"] for x in bootstrap.start_prompts(row["name"], row["repo"], row["description"])}
            if body is None or str(body.get("id", "")) not in ids or type(body.get("done")) is not bool:
                return respond(start, "400 Bad Request", {"error": "invalid_start"})
            conn.execute("INSERT INTO start_state(project_slug,prompt_id,done,ts) VALUES(?,?,?,?) ON CONFLICT(project_slug,prompt_id) DO UPDATE SET done=excluded.done, ts=excluded.ts",
                         (slug, body["id"], 1 if body["done"] else 0, time.time()))
            return respond(start, "200 OK", {"ok": True})
        if sub == "/ideas" and method == "POST":
            body = read_body(environ)
            if body is None:
                return respond(start, "400 Bad Request", {"error": "bad_request"})
            if isinstance(body.get("text"), str):
                text = body["text"].strip()
                if not 1 <= len(text) <= 500:
                    return respond(start, "400 Bad Request", {"error": "invalid_idea"})
                if conn.execute("SELECT count(*) FROM ideas WHERE project_slug=? AND done=0", (slug,)).fetchone()[0] >= 200:
                    return respond(start, "409 Conflict", {"error": "too_many_ideas"})
                cur = conn.execute("INSERT INTO ideas(project_slug,text,created) VALUES(?,?,?)", (slug, text, time.time()))
                return respond(start, "201 Created", {"ok": True, "id": cur.lastrowid})
            if type(body.get("id")) is int and body.get("done") is True:
                conn.execute("UPDATE ideas SET done=1 WHERE project_slug=? AND id=?", (slug, body["id"]))
                return respond(start, "200 OK", {"ok": True})
            return respond(start, "400 Bad Request", {"error": "bad_request"})
        if sub == "/plan" and method == "POST":
            body = read_body(environ)
            plan = body.get("plan") if body else None
            if not isinstance(plan, dict) or "packages" not in plan or "lanes" not in plan or "rules" not in plan:
                return respond(start, "400 Bad Request", {"error": "invalid_plan"})
            try:
                errs = wp.validate(plan)
            except Exception:
                errs = ["неверная структура плана"]
            if errs:
                return respond(start, "422 Unprocessable Entity", {"error": "plan_errors", "details": errs[:20]})
            conn.execute("UPDATE projects SET plan_json=?, plan_updated=? WHERE slug=?", (json.dumps(plan, ensure_ascii=False), time.time(), slug))
            db.audit(conn, "plan.import", {"slug": slug, "packages": len(plan["packages"])})
            return respond(start, "200 OK", {"ok": True, "packages": len(plan["packages"])})
        if sub == "/sync" and method == "POST":
            try:
                plan = json.loads(fetch_plan(row["repo"]))
                errs = wp.validate(plan)
            except Exception as e:
                return respond(start, "502 Bad Gateway", {"error": "sync_failed", "detail": str(e)[:120]})
            if errs:
                return respond(start, "422 Unprocessable Entity", {"error": "plan_errors", "details": errs[:20]})
            conn.execute("UPDATE projects SET plan_json=?, plan_updated=? WHERE slug=?", (json.dumps(plan, ensure_ascii=False), time.time(), slug))
            db.audit(conn, "plan.sync", {"slug": slug})
            return respond(start, "200 OK", {"ok": True, "packages": len(plan["packages"])})
        if sub == "/status" and method == "POST":
            body = read_body(environ)
            if body is None or not row["plan_json"]:
                return respond(start, "400 Bad Request", {"error": "bad_request"})
            plan = json.loads(row["plan_json"])
            pid, status = str(body.get("id", "")), str(body.get("status", ""))
            ids = {p["id"]: p for p in plan["packages"]}
            if pid not in ids or status not in STATUSES:
                return respond(start, "400 Bad Request", {"error": "invalid_status"})
            cur = states(slug).get(pid, {"status": "planned"})
            done = {k for k, v in states(slug).items() if v["status"] == "accepted"}
            if status == "issued" and cur["status"] == "planned" and not all(d in done for d in ids[pid]["depends_on"]):
                return respond(start, "409 Conflict", {"error": "dependencies_not_accepted"})
            now = time.time()
            conn.execute("INSERT OR IGNORE INTO task_state(project_slug,pkg_id) VALUES(?,?)", (slug, pid))
            sets = {"status": status}
            if status == "issued":
                sets["issued_at"] = now
            if status == "submitted":
                sets["submitted_at"] = now
            if status == "accepted":
                sets["accepted_at"] = now
            if status == "planned":
                sets.update(issued_at=None, submitted_at=None, accepted_at=None, merged=0, sha="")
            if "merged" in body:
                sets["merged"] = 1 if body["merged"] is True else 0
            if isinstance(body.get("sha"), str) and re.fullmatch(r"[0-9a-f]{7,40}", body["sha"]):
                sets["sha"] = body["sha"]
            if isinstance(body.get("note"), str):
                sets["note"] = body["note"][:300]
            conn.execute("UPDATE task_state SET " + ",".join(f"{k}=?" for k in sets) + " WHERE project_slug=? AND pkg_id=?", (*sets.values(), slug, pid))
            db.audit(conn, "task.status", {"slug": slug, "id": pid, "status": status})
            return respond(start, "200 OK", {"ok": True})
        return respond(start, "404 Not Found", {"error": "not_found"})

    app.close = conn.close
    return app
