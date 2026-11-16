"""WSGI-приложение портала CreatePortal. Префикс (например /createportal) срезается; JSON API под /api, одна HTML-страница."""
from __future__ import annotations

import threading

import json
import hmac
import hashlib
import os
import re
import secrets
import time
import urllib.request
from http.cookies import SimpleCookie
from pathlib import Path

from . import auth, bootstrap, db
from .hooks import github
from tools import work_plan as wp  # общие проверка плана и генерация промптов

MAX_BODY = 1_000_000
STATUSES = ("planned", "issued", "submitted", "accepted")
COOKIE = "portal_session"
STATIC = Path(__file__).with_name("static")


def _prompted(plan):
    return [dict(p, prompt=wp.prompt(plan, p["id"])) for p in plan["packages"]]


def create_app(db_path, base="", secure_cookie=True, fetch=None, github_token_file=None, security_v2=True, webhook_enabled=False, webhook_secret_file=None, reports_enabled=False):
    conn = db.connect(db_path, webhook=webhook_enabled or reports_enabled, reports=reports_enabled)
    base = base.rstrip("/")

    review_template = ["Пробное слияние без конфликтов", "Изменены только файлы зоны", "Тесты директора прошли", "CI зелёный", "Слито в main"]

    def task_exists(row, pid):
        if not row["plan_json"]:
            return False
        return any(p.get("id") == pid for p in json.loads(row["plan_json"]).get("packages", []))

    def record_event(slug, pid, kind, payload=None):
        # Never store arbitrary user text, credentials or tokens in the event log.
        safe = {k: v for k, v in (payload or {}).items() if k in ("count", "manual", "status") and (type(v) in (int, bool) or (isinstance(v, str) and v in STATUSES))}
        conn.execute("INSERT INTO events(project_slug,pkg_id,ts,kind,source,payload) VALUES(?,?,?,?,?,?)",
                     (slug, pid, time.time(), kind, "portal", json.dumps(safe)))

    def metrics(slug=None):
        where = " WHERE project_slug=?" if slug else ""
        args = (slug,) if slug else ()
        tasks = conn.execute("SELECT project_slug,pkg_id,status,issued_at,submitted_at,accepted_at FROM task_state" + where, args).fetchall()
        reviews = conn.execute("SELECT project_slug,pkg_id,revision_count,ci_state FROM task_reviews" + where, args).fetchall()
        now = time.time()
        durations_submit = [r["submitted_at"]-r["issued_at"] for r in tasks if r["submitted_at"] is not None and r["issued_at"] is not None and r["submitted_at"] >= r["issued_at"]]
        durations_accept = [r["accepted_at"]-r["submitted_at"] for r in tasks if r["accepted_at"] is not None and r["submitted_at"] is not None and r["accepted_at"] >= r["submitted_at"]]
        accepted = sum(r["status"] == "accepted" and r["accepted_at"] is not None and r["accepted_at"] >= now-7*86400 for r in tasks)
        returned = sum(r["revision_count"] > 0 for r in reviews)
        reviewed = {(r["project_slug"], r["pkg_id"]): r for r in reviews}
        total = len({(r["project_slug"], r["pkg_id"]) for r in tasks} | set(reviewed))
        return {"accepted_week": accepted, "avg_issue_to_submit_seconds": sum(durations_submit)/len(durations_submit) if durations_submit else None,
                "avg_submit_to_accept_seconds": sum(durations_accept)/len(durations_accept) if durations_accept else None,
                "return_rate": returned/total if total else 0, "returned_tasks": returned, "total_tasks": total,
                "awaiting_owner": sum(r["status"] == "submitted" for r in tasks),
                "red_ci": sum(r["ci_state"] in ("failure", "failed", "red") for r in reviews) + conn.execute("SELECT COUNT(*) FROM pr_links WHERE ci_state IN ('failure','failed','red')" + (" AND project_slug=?" if slug else ""), args).fetchone()[0]}

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
        result = {r["pkg_id"]: {k: r[k] for k in ("status", "issued_at", "submitted_at", "accepted_at", "merged", "sha", "note")}
                  for r in conn.execute("SELECT * FROM task_state WHERE project_slug=?", (slug,))}
        if webhook_enabled:
            for link in conn.execute('SELECT * FROM pr_links WHERE project_slug=? ORDER BY updated', (slug,)):
                result.setdefault(link['pkg_id'], {'status': 'planned', 'issued_at': None, 'submitted_at': None,
                                                     'accepted_at': None, 'merged': 0, 'sha': '', 'note': ''})
                result[link['pkg_id']]['pr'] = {'number': link['pr_number'], 'branch': link['branch'], 'state': link['state'],
                                                'sha': link['sha'], 'merged': link['state'] == 'merged'}
                result[link['pkg_id']]['ci'] = {'state': link['ci_state'], 'sha': link['sha']}
        return result

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

    def handle(environ, start):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/")
        if base and path.startswith(base):
            path = path[len(base):] or "/"
        remote = (environ.get("REMOTE_ADDR") or "-")[:64]
        # X-Real-IP доверяем только от локального прокси (nginx сам перезаписывает его адресом клиента); иначе всё за прокси считалось бы одним IP
        ip = (environ.get("HTTP_X_REAL_IP") or remote)[:64] if remote in ("127.0.0.1", "::1") else remote
        try:
            cookies = SimpleCookie(environ.get("HTTP_COOKIE", "")[:4096])
        except Exception:
            cookies = SimpleCookie()
        token = cookies[COOKIE].value if COOKIE in cookies else ""
        if path == "/hook/github" and method == "POST":
            if not webhook_enabled:
                return respond(start, "404 Not Found", {"error": "not_found"})
            try:
                secret = Path(webhook_secret_file).read_bytes().strip() if webhook_secret_file else b''
            except OSError:
                secret = b''
            try:
                length = int(environ.get('CONTENT_LENGTH', '0'))
            except (ValueError, TypeError):
                length = -1
            if length < 0 or length > MAX_BODY:
                return respond(start, "413 Payload Too Large", {"error": "body_size"})
            raw = environ['wsgi.input'].read(length)
            if len(raw) != length:
                return respond(start, '400 Bad Request', {'error': 'incomplete_body'})
            if not secret or not github.verified(raw, environ.get('HTTP_X_HUB_SIGNATURE_256'), secret):
                return respond(start, "401 Unauthorized", {"error": "invalid_signature"})
            delivery = environ.get('HTTP_X_GITHUB_DELIVERY', '')
            kind = environ.get('HTTP_X_GITHUB_EVENT', '')
            if not github.DELIVERY.fullmatch(delivery) or kind not in ('push', 'pull_request', 'check_suite', 'workflow_run'):
                return respond(start, "400 Bad Request", {"error": "invalid_event"})
            try:
                payload = json.loads(raw)
                result = github.process(conn, kind, payload, delivery, fetch_plan=fetch_plan)
            except (ValueError, TypeError, KeyError):
                return respond(start, "400 Bad Request", {"error": "invalid_payload"})
            return respond(start, "200 OK", {"ok": True, "result": result})
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
        if reports_enabled and path == "/api/metrics" and method == "GET":
            return respond(start, "200 OK", {"metrics": metrics()})
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
        if reports_enabled:
            task_match = re.fullmatch(r"/api/projects/([a-z][a-z0-9-]{1,38}[a-z0-9])/tasks/([A-Za-z][A-Za-z0-9_-]{0,39})/(report|review)", path)
            if task_match:
                slug, pid, kind = task_match.groups()
                project = project_row(slug)
                if not project or not task_exists(project, pid):
                    return respond(start, "404 Not Found", {"error": "task_not_found"})
                if method == "GET":
                    if kind == "report":
                        r = conn.execute("SELECT body,pr_url,updated FROM task_reports WHERE project_slug=? AND pkg_id=?", (slug,pid)).fetchone()
                        return respond(start, "200 OK", {"report": dict(r) if r else None})
                    r = conn.execute("SELECT items,ci_state,revision_count,remarks,updated FROM task_reviews WHERE project_slug=? AND pkg_id=?", (slug,pid)).fetchone()
                    return respond(start, "200 OK", {"review": {**dict(r), "items": json.loads(r["items"])} if r else {"items": [{"text": x, "checked": False} for x in review_template], "ci_state": "unknown", "revision_count": 0, "remarks": ""}})
                if method != "POST":
                    return respond(start, "405 Method Not Allowed", {"error": "method_not_allowed"})
                body = read_body(environ)
                if body is None:
                    return respond(start, "400 Bad Request", {"error": "bad_request"})
                now = time.time()
                if kind == "report":
                    if not set(body) <= {"text", "pr_url"} or not body:
                        return respond(start, "400 Bad Request", {"error": "invalid_report"})
                    txt, url = body.get("text", ""), body.get("pr_url", "")
                    if type(txt) is not str or len(txt) > 20000 or type(url) is not str or len(url) > 300 or (url and not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*", url)) or not (txt.strip() or url):
                        return respond(start, "400 Bad Request", {"error": "invalid_report"})
                    conn.execute("INSERT INTO task_reports(project_slug,pkg_id,body,pr_url,updated) VALUES(?,?,?,?,?) ON CONFLICT(project_slug,pkg_id) DO UPDATE SET body=excluded.body,pr_url=excluded.pr_url,updated=excluded.updated", (slug,pid,txt,url,now))
                    record_event(slug,pid,"task.report")
                    return respond(start, "200 OK", {"ok": True})
                if not set(body) <= {"items", "ci_state", "return", "remarks"} or not body:
                    return respond(start, "400 Bad Request", {"error": "invalid_review"})
                old = conn.execute("SELECT * FROM task_reviews WHERE project_slug=? AND pkg_id=?", (slug,pid)).fetchone()
                items = body.get("items", json.loads(old["items"]) if old else [{"text": x, "checked": False} for x in review_template])
                ci = body.get("ci_state", old["ci_state"] if old else "unknown")
                returning = body.get("return", False)
                remarks = body.get("remarks", old["remarks"] if old else "")
                if (not isinstance(items,list) or not 1 <= len(items) <= 30 or any(not isinstance(x,dict) or set(x)!={"text","checked"} or type(x["text"]) is not str or not 1 <= len(x["text"]) <= 150 or type(x["checked"]) is not bool for x in items)
                    or ci not in ("unknown", "pending", "success", "failure", "red", "failed") or type(ci) is not str or type(returning) is not bool or type(remarks) is not str or len(remarks) > 3000):
                    return respond(start, "400 Bad Request", {"error": "invalid_review"})
                if returning and not remarks.strip():
                    return respond(start, "400 Bad Request", {"error": "remarks_required"})
                if returning:
                    cur = conn.execute("SELECT status FROM task_state WHERE project_slug=? AND pkg_id=?", (slug,pid)).fetchone()
                    if not cur or cur["status"] != "submitted":
                        return respond(start, "409 Conflict", {"error": "task_not_submitted"})
                count = (old["revision_count"] if old else 0) + int(returning)
                conn.execute("INSERT INTO task_reviews(project_slug,pkg_id,items,ci_state,revision_count,remarks,updated) VALUES(?,?,?,?,?,?,?) ON CONFLICT(project_slug,pkg_id) DO UPDATE SET items=excluded.items,ci_state=excluded.ci_state,revision_count=excluded.revision_count,remarks=excluded.remarks,updated=excluded.updated", (slug,pid,json.dumps(items,ensure_ascii=False),ci,count,remarks,now))
                if returning:
                    conn.execute("UPDATE task_state SET status='issued',submitted_at=NULL,accepted_at=NULL WHERE project_slug=? AND pkg_id=?", (slug,pid))
                    db.audit(conn,"task.revision",{"slug":slug,"id":pid,"count":count})
                    record_event(slug,pid,"task.revision",{"count":count})
                else:
                    record_event(slug,pid,"task.review")
                return respond(start, "200 OK", {"ok": True, "revision_count": count})
            metric_match = re.fullmatch(r"/api/projects/([a-z][a-z0-9-]{1,38}[a-z0-9])/metrics", path)
            if metric_match and method == "GET":
                slug = metric_match.group(1)
                if not project_row(slug):
                    return respond(start,"404 Not Found",{"error":"no_project"})
                return respond(start,"200 OK",{"metrics":metrics(slug)})
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
        if (webhook_enabled or reports_enabled) and sub == "/events" and method == "GET":
            entries = []
            for e in conn.execute('SELECT id,pkg_id,ts,kind,source,payload FROM events WHERE project_slug=? ORDER BY id DESC LIMIT 200', (slug,)):
                entries.append({'id': e['id'], 'pkg_id': e['pkg_id'], 'ts': e['ts'], 'kind': e['kind'],
                                'source': e['source'], 'payload': json.loads(e['payload'])})
            return respond(start, "200 OK", {"events": entries})
        if webhook_enabled and sub == "/settings":
            if method == "GET":
                return respond(start, "200 OK", github.settings(conn, slug))
            if method == "POST":
                body = read_body(environ)
                if body is None or not body or not set(body) <= {'auto_accept', 'auto_accept_require_checklist', 'required_checks'}:
                    return respond(start, "400 Bad Request", {"error": "invalid_settings"})
                if any(type(v) is not bool for k,v in body.items() if k != 'required_checks'):
                    return respond(start, "400 Bad Request", {"error": "invalid_settings"})
                checks = body.get('required_checks', github.settings(conn, slug)['required_checks'])
                if not isinstance(checks, list) or len(checks) > 30 or any(not isinstance(x, str) or not 1 <= len(x) <= 100 for x in checks):
                    return respond(start, "400 Bad Request", {"error": "invalid_settings"})
                cfg = github.settings(conn, slug)
                cfg.update(body)
                conn.execute('INSERT INTO project_settings(project_slug,auto_accept,auto_accept_require_checklist,required_checks) VALUES(?,?,?,?) ON CONFLICT(project_slug) DO UPDATE SET auto_accept=excluded.auto_accept,auto_accept_require_checklist=excluded.auto_accept_require_checklist,required_checks=excluded.required_checks',
                             (slug, int(cfg['auto_accept']), int(cfg['auto_accept_require_checklist']), json.dumps(checks)))
                github.event(conn, slug, None, 'settings.changed', source='portal')
                return respond(start, "200 OK", github.settings(conn, slug))
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
            if reports_enabled and status == "accepted" and cur["status"] != "accepted":
                manual = body.get("manual", False)
                if type(manual) is not bool:
                    return respond(start, "400 Bad Request", {"error": "invalid_manual"})
                review = conn.execute("SELECT items,ci_state FROM task_reviews WHERE project_slug=? AND pkg_id=?", (slug,pid)).fetchone()
                if not manual:
                    if not review or not all(x.get("checked") is True for x in json.loads(review["items"])):
                        return respond(start, "409 Conflict", {"error": "checklist_incomplete", "reason": "Отметьте все пункты приёмки"})
                    red = review["ci_state"] in ("failure", "failed", "red")
                    linked = conn.execute("SELECT 1 FROM pr_links WHERE project_slug=? AND pkg_id=? AND ci_state IN ('failure','failed','red') LIMIT 1", (slug,pid)).fetchone()
                    if red or linked:
                        return respond(start, "409 Conflict", {"error": "ci_red", "reason": "CI красный: исправьте проверки или примите вручную"})
                else:
                    db.audit(conn,"task.manual_accept",{"slug":slug,"id":pid,"manual":1})
                    record_event(slug,pid,"task.manual_accept",{"manual":True})
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
            if reports_enabled:
                record_event(slug,pid,"task.status",{"status":status})
            return respond(start, "200 OK", {"ok": True})
        return respond(start, "404 Not Found", {"error": "not_found"})

    lock = threading.Lock()  # одно соединение SQLite на все потоки сервера: запросы обрабатываются по очереди (владелец один)

    def app(environ, start):
        with lock:
            return handle(environ, start)

    app.close = conn.close
    return app
