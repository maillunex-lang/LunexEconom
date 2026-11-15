"""Game administration API: monitoring, moderation, announcements. See docs/ADMIN.md.

Exposed only on the game server's loopback listener (`request_allowed`): the public nginx prefix adds `X-Real-IP`, which makes a request
inadmissible here even with a valid token. It never edits money, wallets, buildings or any economy constant. Shared by SQLite and PostgreSQL
(`ph` is the SQL placeholder). Tables `adm_*` are created by `ensure()` at startup (like `soc_*`).
"""
import hashlib
import hmac
import os
import re
import threading
import time

import clock

TOKEN_ENV = "LUNEX_GAME_ADMIN_TOKEN"
MIN_TOKEN = 32
PROXY_HEADERS = ("X-Real-IP", "X-Forwarded-For", "X-Forwarded-Host", "Forwarded", "X-Forwarded-Proto")
LOOPBACK = ("127.0.0.1", "::1")
MAX_ANNOUNCEMENT = 200
FAIL_LIMIT, FAIL_WINDOW = 10, 300
_fails = []
_fail_lock = threading.Lock()
SERVER_STARTED = time.monotonic()
SYSTEM_ACCOUNTS = ("system:treasury", "system:market", "system:bank", "system:residents", "system:upkeep", "system:construction", "player:city")

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS adm_audit(id INTEGER PRIMARY KEY, at BIGINT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL, detail TEXT NOT NULL, ip TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS adm_announcement(id INTEGER PRIMARY KEY, text TEXT NOT NULL, updated BIGINT NOT NULL, actor TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS adm_report_state(report_id TEXT PRIMARY KEY, status TEXT NOT NULL, note TEXT NOT NULL, resolved_by TEXT NOT NULL, resolved_at BIGINT NOT NULL)",
)
PG_ONLY = (
    # PostgreSQL keeps accounts and the world in one database, SQLite keeps accounts in their own file (auth._prepare_sqlite creates it there).
    "CREATE TABLE IF NOT EXISTS adm_bans (username TEXT PRIMARY KEY, reason TEXT NOT NULL, banned_at BIGINT NOT NULL, until BIGINT, actor TEXT NOT NULL)",
)


def _q(sql, ph):
    return sql.replace("%s", ph)


def ensure(db, ph, postgres=False):
    statements = SCHEMA
    if postgres:
        statements = SCHEMA + PG_ONLY
    for statement in statements:
        if postgres:
            statement = statement.replace("id INTEGER PRIMARY KEY", "id BIGSERIAL PRIMARY KEY") if "adm_audit" in statement else statement
        db.execute(statement)


# ---------- access control ----------
def enabled():
    return len(os.environ.get(TOKEN_ENV, "")) >= MIN_TOKEN


def request_allowed(headers, client_ip):
    """Loopback only, and never a request that went through a reverse proxy; disabled without a long token."""
    if not enabled() or client_ip not in LOOPBACK:
        return False
    return not any(headers.get(name) for name in PROXY_HEADERS)


def _throttled(now):
    with _fail_lock:
        _fails[:] = [t for t in _fails if now - t < FAIL_WINDOW]
        return len(_fails) >= FAIL_LIMIT


def note_failure(now):
    with _fail_lock:
        _fails.append(now)


def clear_failures():
    with _fail_lock:
        _fails.clear()


def token_ok(authorization, now):
    """(ok, throttled). Constant-time comparison on bytes (non-ASCII input cannot raise)."""
    if _throttled(now):
        return False, True
    expected = ("Bearer " + os.environ.get(TOKEN_ENV, "")).encode("utf-8")
    given = str(authorization or "").encode("utf-8", "replace")
    if hmac.compare_digest(hashlib.sha256(given).digest(), hashlib.sha256(expected).digest()):
        return True, False
    note_failure(now)
    return False, False


# ---------- helpers ----------
def _scalar(db, sql, params=()):
    # No parameters -> no placeholder processing: a literal % (LIKE 'town:%') must reach psycopg untouched.
    row = (db.execute(sql, params) if params else db.execute(sql)).fetchone()
    return 0 if row is None or row[0] is None else row[0]


def _month(db, now):
    row = db.execute("SELECT epoch,month_seconds,base_index FROM world_clock WHERE id=1").fetchone()
    if row is None:
        return None, None
    return clock.month_index((int(row[0]), int(row[1]), int(row[2])), now), int(row[1])


def audit(db, ph, actor, action, target, detail, ip, now):
    db.execute(_q("INSERT INTO adm_audit(at,actor,action,target,detail,ip) VALUES(%s,%s,%s,%s,%s,%s)", ph),
               (now, str(actor)[:64], action, str(target)[:64], str(detail)[:300], str(ip)[:64]))


def _clean_text(value, limit):
    text = str(value or "").strip()
    if len(text) > limit or any(ord(c) < 32 for c in text) or "<" in text or ">" in text:
        return None
    return text


# ---------- public ----------
def announcement(db, ph):
    row = db.execute("SELECT text,updated FROM adm_announcement WHERE id=1").fetchone()
    import runtime_config
    maintenance = bool(runtime_config.values(db).get("MAINTENANCE_MODE", runtime_config._initial("MAINTENANCE_MODE")))
    if row is None or not row[0]:
        return 200, {"text": "", "updated": 0, "maintenance": maintenance}
    return 200, {"text": row[0], "updated": int(row[1]), "maintenance": maintenance}


# ---------- read-only ----------
def overview(db, ph, now, extra):
    month, month_seconds = _month(db, now)
    accounts = {name: int(_scalar(db, _q("SELECT balance FROM wallets WHERE account=%s", ph), (name,))) for name in SYSTEM_ACCOUNTS}
    result = {
        "ok": True, "now": now, "month_index": month, "month_seconds": month_seconds,
        "accounts": extra,
        "world": {
            "buildings": int(_scalar(db, "SELECT COUNT(*) FROM buildings WHERE owner NOT LIKE 'town:%'")),
            "town_houses": int(_scalar(db, "SELECT COUNT(*) FROM buildings WHERE owner LIKE 'town:%'")),
            "companies": int(_scalar(db, "SELECT COUNT(DISTINCT owner) FROM building_ops")),
            "roads": int(_scalar(db, "SELECT COUNT(*) FROM roads")),
        },
        "ledger": {
            "transactions": int(_scalar(db, "SELECT COUNT(*) FROM ledger_tx")),
            "unbalanced_transactions": int(_scalar(db, "SELECT COUNT(*) FROM (SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0) x")),
            "wallet_sum": int(_scalar(db, "SELECT COALESCE(SUM(balance),0) FROM wallets")),
        },
        "system_accounts": accounts,
        "finance": {
            "loans_outstanding": int(_scalar(db, "SELECT COALESCE(SUM(balance),0) FROM loans")),
            "bankruptcies": int(_scalar(db, "SELECT COALESCE(SUM(bankruptcies),0) FROM company_status")),
            "companies_in_arrears": int(_scalar(db, "SELECT COUNT(*) FROM company_status WHERE missed>0")),
        },
    }
    row = db.execute("SELECT month_index,population,jobs,wage FROM population ORDER BY month_index DESC LIMIT 1").fetchone()
    result["city"] = None if row is None else {"month_index": int(row[0]), "population": int(row[1]), "jobs": int(row[2]), "wage": int(row[3])}
    last = db.execute("SELECT MAX(month_index) FROM market_prices").fetchone()[0]
    prices = {}
    if last is not None:
        for product, price in db.execute(_q("SELECT product,price FROM market_prices WHERE month_index=%s ORDER BY product", ph), (last,)).fetchall():
            prices[product] = int(price)
    result["prices"] = {"month_index": None if last is None else int(last), "products": prices}
    try:
        result["moderation"] = {
            "open_reports": int(_scalar(db, "SELECT COUNT(*) FROM soc_reports r LEFT JOIN adm_report_state s ON s.report_id=r.id WHERE s.report_id IS NULL")),
            "alliances": int(_scalar(db, "SELECT COUNT(*) FROM soc_alliances")),
        }
    except Exception:       # social tables may be absent in a bare database
        result["moderation"] = {"open_reports": 0, "alliances": 0}
    result["warnings"] = [text for ok, text in (
        (result["ledger"]["unbalanced_transactions"] == 0, "В журнале есть несбалансированные проводки"),
        (result["ledger"]["wallet_sum"] == 0, "Сумма кошельков не равна нулю"),
    ) if not ok]
    return 200, result


def player(db, ph, name, ban):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", name or ""):
        return 400, {"error": "invalid_name"}
    account = "player:" + name
    balance = db.execute(_q("SELECT balance FROM wallets WHERE account=%s", ph), (account,)).fetchone()
    buildings = {kind: int(n) for kind, n in db.execute(_q("SELECT kind,COUNT(*) FROM buildings WHERE owner=%s GROUP BY kind ORDER BY kind", ph), (name,)).fetchall()}
    status = db.execute(_q("SELECT missed,bankruptcies,wages_owed,input_owed,maint_owed FROM company_status WHERE owner=%s", ph), (name,)).fetchone()
    tax = db.execute(_q("SELECT tax_owed FROM company_tax_state WHERE owner=%s", ph), (name,)).fetchone()
    loan = db.execute(_q("SELECT balance FROM loans WHERE owner=%s", ph), (name,)).fetchone()
    recent = [{"at": int(t[0]), "memo": t[1], "amount": int(t[2])} for t in db.execute(_q(
        "SELECT t.created,t.memo,e.amount FROM ledger_entries e JOIN ledger_tx t ON t.id=e.tx_id WHERE e.account=%s ORDER BY t.created DESC LIMIT 15", ph), (account,)).fetchall()]
    try:
        reports_against = int(_scalar(db, _q("SELECT COUNT(*) FROM soc_reports WHERE target=%s", ph), (name,)))
    except Exception:
        reports_against = 0
    return 200, {"ok": True, "username": name, "balance": None if balance is None else int(balance[0]), "buildings": buildings,
                 "company": None if status is None else {"missed": int(status[0]), "bankruptcies": int(status[1]), "arrears": int(status[2] + status[3] + status[4] + (0 if tax is None else tax[0]))},
                 "loan": 0 if loan is None else int(loan[0]), "recent_transactions": recent, "reports_against": reports_against, "ban": ban}


def players(db, ph, users):
    """`users` come from the accounts database (auth.list_users); enrich with the world data."""
    out = []
    for user in users:
        name = user["username"]
        balance = db.execute(_q("SELECT balance FROM wallets WHERE account=%s", ph), (("player:" + name),)).fetchone()
        buildings = int(_scalar(db, _q("SELECT COUNT(*) FROM buildings WHERE owner=%s", ph), (name,)))
        out.append({**user, "balance": None if balance is None else int(balance[0]), "buildings": buildings})
    return 200, {"ok": True, "players": out}


def reports(db, ph, status):
    where = "" if status == "all" else "WHERE s.report_id IS NULL"
    try:
        rows = db.execute("SELECT r.id,r.reporter,r.target,r.reason,r.created,s.status,s.note FROM soc_reports r LEFT JOIN adm_report_state s ON s.report_id=r.id "
                          + where + " ORDER BY r.created DESC LIMIT 100").fetchall()
    except Exception:
        rows = []
    return 200, {"ok": True, "reports": [{"id": r[0], "reporter": r[1], "target": r[2], "reason": r[3], "created": int(r[4]), "status": r[5] or "open", "note": r[6] or ""} for r in rows]}


def audit_view(db, ph):
    rows = db.execute("SELECT at,actor,action,target,detail,ip FROM adm_audit ORDER BY id DESC LIMIT 100").fetchall()
    return 200, {"ok": True, "audit": [{"at": int(r[0]), "actor": r[1], "action": r[2], "target": r[3], "detail": r[4], "ip": r[5]} for r in rows]}


# ---------- changes (all audited) ----------
def resolve_report(db, ph, payload, actor, ip, now):
    report_id = str(payload.get("id", ""))
    status = payload.get("status")
    note = _clean_text(payload.get("note", ""), 300)
    if status not in ("dismissed", "actioned") or note is None or not report_id or len(report_id) > 64:
        return 400, {"error": "invalid_request"}
    if db.execute(_q("SELECT 1 FROM soc_reports WHERE id=%s", ph), (report_id,)).fetchone() is None:
        return 404, {"error": "report_not_found"}
    db.execute(_q("DELETE FROM adm_report_state WHERE report_id=%s", ph), (report_id,))
    db.execute(_q("INSERT INTO adm_report_state(report_id,status,note,resolved_by,resolved_at) VALUES(%s,%s,%s,%s,%s)", ph), (report_id, status, note, str(actor)[:64], now))
    audit(db, ph, actor, "report_" + status, report_id, note, ip, now)
    return 200, {"ok": True}


def set_announcement(db, ph, payload, actor, ip, now):
    text = _clean_text(payload.get("text", ""), MAX_ANNOUNCEMENT)
    if text is None:
        return 400, {"error": "invalid_text"}
    db.execute("DELETE FROM adm_announcement WHERE id=1")
    if text:
        db.execute(_q("INSERT INTO adm_announcement(id,text,updated,actor) VALUES(1,%s,%s,%s)", ph), (text, now, str(actor)[:64]))
    audit(db, ph, actor, "announcement_set" if text else "announcement_clear", "-", text, ip, now)
    return 200, {"ok": True, "text": text}


def seed_cities(db, ph, payload, actor, ip, now):
    """Initial city generation (docs/CITYGEN.md). `city_id`: an id or "all"; `dry_run` defaults to TRUE so a plan is always seen first."""
    import citygen
    import geo
    which = payload.get("city_id")
    known = {c["id"] for c in geo.cities()}
    if which != "all" and which not in known:
        return 400, {"error": "unknown_city"}
    dry = payload.get("dry_run", True) is not False
    first = citygen.is_first_generation(db, ph)
    counts = citygen.world_counts(db, ph) if first else {}
    try:
        result = citygen.seed(db, ph, "all" if which == "all" else [which], now, dry_run=dry, wipe=payload.get("wipe") is True)
    except citygen.WipeRequired as error:
        return 409, {"error": "wipe_required", "counts": error.counts,
                     "message": "The first generation erases the whole game world (accounts stay). Make a backup and repeat with \"wipe\": true."}
    if not dry:
        wiped = first and any(counts.values())
        audit(db, ph, actor, "cities_seed", str(which), "houses placed: %d%s" % (sum(r["placed"] for r in result), "; WORLD ERASED first: %s" % counts if wiped else ""), ip, now)
    return 200, {"ok": True, "dry_run": dry, "first_generation": first, "wipes_world": first, "world_counts": counts, "cities": result}


# ---------- dispatch ----------
def handle(db, ph, method, path, args, payload, ctx, now, auth):
    """One administrative request. `auth` is the accounts module (users, bans). Returns (status, result)."""
    actor, ip = ctx.get("actor", "admin"), ctx.get("ip", "-")
    if method == "GET":
        # BEGIN ChatGPT13 administration (loopback + token enforced by Handler)
        if path in ("/admin/config", "/admin/revisions", "/admin/online",
                    "/admin/status", "/admin/online/players", "/admin/config/candidate"):
            import runtime_config, presence
            if path == "/admin/config/candidate":
                import live_config_api
                return 200, {"ok": True, **live_config_api.prepare_candidate(db)}
            if path == "/admin/config":
                return 200, {"ok": True, **runtime_config.describe(db, now),
                             "client": runtime_config.client_settings(db)}
            if path == "/admin/revisions":
                return 200, {"ok": True, "revisions": runtime_config.revisions(db)}
            if path == "/admin/online":
                return 200, {"ok": True, **presence.summary(db, ph, now),
                             "history": presence.history(db, ph, now)}
            if path == "/admin/online/players":
                return 200, {"ok": True, "players": presence.players(db, ph, now)}
            import os
            import json
            from pathlib import Path
            state = runtime_config.snapshot(db)
            # Do not expose paths, credentials or raw process environment.
            import importlib.util
            import re
            sha_path = os.environ.get("LUNEX_DEPLOYED_SHA_FILE",
                "/var/lib/lunexeconom-server-update/deployed-sha")
            try:
                sha = Path(sha_path).read_text(encoding="ascii").strip()
                sha = sha[:12] if re.fullmatch(r"[0-9a-fA-F]{40}", sha) else None
            except (OSError, UnicodeError, ValueError):
                sha = None
            releases = db.execute("SELECT revision FROM signed_live_config WHERE id=1").fetchone()
            clock_info = db.execute("SELECT epoch,month_seconds,base_index FROM world_clock WHERE id=1").fetchone()
            next_ms = None
            if clock_info is not None:
                next_ms = (int(clock_info[1]) - ((now - int(clock_info[0])) % int(clock_info[1]))) * 1000
            return 200, {"ok": True, "version": "0.2.0", "commit": sha,
                         "uptime_seconds": max(0, int(time.monotonic() - SERVER_STARTED)),
                         "database": {"status": "ok"},
                         "revision": state["revision"], "month": runtime_config.current_month(db, now),
                         "month_next_step_ms": next_ms,
                         "online": presence.summary(db, ph, now),
                         "accounts": auth.admin_counts(),
                         "errors_24h": None, "backup_age_seconds": None,
                         "client_config_revision": int(releases[0]) if releases else None,
                         "config": {k: v for k, v in runtime_config.values(db).items()
                                    if k not in runtime_config.CLIENT_FLAGS},
                         "client": runtime_config.client_settings(db)}
        # END ChatGPT13 administration
        if path == "/admin/overview":
            return overview(db, ph, now, auth.admin_counts())
        if path == "/admin/players":
            try:
                limit = int(args.get("limit", "50"))
            except ValueError:
                return 400, {"error": "invalid_query"}
            return players(db, ph, auth.list_users(args.get("q", ""), limit))
        if path == "/admin/player":
            name = args.get("name", "")
            ban = None
            for user in auth.list_users(name, 5):
                if user["username"] == name and user["banned"]:
                    ban = {"reason": user["ban_reason"], "until": user["ban_until"]}
            return player(db, ph, name, ban)
        if path == "/admin/reports":
            return reports(db, ph, "all" if args.get("status") == "all" else "open")
        if path == "/admin/audit":
            return audit_view(db, ph)
        if path == "/admin/cities":
            import citygen
            return 200, {"ok": True, "cities": citygen.status(db, ph)}
        return 404, {"error": "not_found"}
    # BEGIN ChatGPT13 protected runtime mutations
    if path in ("/admin/config/set", "/admin/config/rollback", "/admin/config/client", "/admin/config/sign"):
        import runtime_config
        try:
            if path == "/admin/config/sign":
                import live_config_api
                result = live_config_api.publish(db, ph, actor, ip, now, payload)
            elif path == "/admin/config/set":
                result = runtime_config.change(db, ph, payload.get("changes"), actor, ip, now,
                                               payload.get("comment", ""),
                                               payload.get("confirm") is True,
                                               payload.get("expected_revision"))
            elif path == "/admin/config/rollback":
                result = runtime_config.rollback(db, ph, payload.get("revision"), actor, ip, now,
                                                 payload.get("confirm") is True,
                                                 payload.get("expected_revision"))
            else:
                result = runtime_config.client_update(db, ph, payload.get("changes"), actor, ip, now,
                                                      payload.get("confirm") is True, payload.get("expected_revision"))
            return 200, {"ok": True, **result}
        except ValueError as exc:
            error = str(exc)
            return (409 if error == "revision_conflict" else 400), {"error": error}
    # END ChatGPT13 protected runtime mutations
    if path == "/admin/ban":
        status, result = auth.ban_user(payload.get("username"), payload.get("reason"), payload.get("days"), actor)
        if status == 200:
            audit(db, ph, actor, "ban", result["username"], str(payload.get("reason"))[:200], ip, now)
        return status, result
    if path == "/admin/unban":
        status, result = auth.unban_user(payload.get("username"))
        if status == 200:
            audit(db, ph, actor, "unban", result["username"], "-", ip, now)
        return status, result
    if path == "/admin/report/resolve":
        return resolve_report(db, ph, payload, actor, ip, now)
    if path == "/admin/announce":
        return set_announcement(db, ph, payload, actor, ip, now)
    if path == "/admin/cities/seed":
        return seed_cities(db, ph, payload, actor, ip, now)
    return 404, {"error": "not_found"}
