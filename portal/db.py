"""SQLite-хранилище портала. Один владелец, несколько проектов."""
from __future__ import annotations

import json
import sqlite3
import time
import re

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, pw_hash TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, csrf TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY, ip TEXT NOT NULL, ts REAL NOT NULL);
CREATE INDEX IF NOT EXISTS attempts_ip ON attempts(ip, ts);
CREATE TABLE IF NOT EXISTS projects(slug TEXT PRIMARY KEY, name TEXT NOT NULL, repo TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
  plan_json TEXT, plan_updated REAL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS task_state(project_slug TEXT NOT NULL, pkg_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'planned',
  issued_at REAL, submitted_at REAL, accepted_at REAL, merged INTEGER NOT NULL DEFAULT 0, sha TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(project_slug, pkg_id));
CREATE TABLE IF NOT EXISTS ideas(id INTEGER PRIMARY KEY, project_slug TEXT NOT NULL, text TEXT NOT NULL, created REAL NOT NULL, done INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS ideas_project ON ideas(project_slug, done);
CREATE TABLE IF NOT EXISTS start_state(project_slug TEXT NOT NULL, prompt_id TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, ts REAL, PRIMARY KEY(project_slug, prompt_id));
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, ts REAL NOT NULL, action TEXT NOT NULL, payload TEXT NOT NULL);
"""


# Append-only versioned upgrades; legacy tables predate the version ledger.
MIGRATIONS = (
    (1, SCHEMA),
    (2, """CREATE INDEX IF NOT EXISTS audit_recent ON audit(id DESC);
CREATE INDEX IF NOT EXISTS attempts_recent ON attempts(ts);"""),
    (3, """ALTER TABLE projects ADD COLUMN branch TEXT NOT NULL DEFAULT 'main';
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, project_slug TEXT NOT NULL, pkg_id TEXT, ts REAL NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS events_project ON events(project_slug,id DESC);
CREATE TABLE IF NOT EXISTS pr_links(project_slug TEXT NOT NULL, pkg_id TEXT NOT NULL, pr_number INTEGER NOT NULL, branch TEXT NOT NULL, sha TEXT NOT NULL DEFAULT '', state TEXT NOT NULL, ci_state TEXT NOT NULL DEFAULT 'pending', updated REAL NOT NULL, base_branch TEXT NOT NULL DEFAULT '', PRIMARY KEY(project_slug,pr_number));
CREATE INDEX IF NOT EXISTS pr_task ON pr_links(project_slug,pkg_id);
CREATE TABLE IF NOT EXISTS webhook_deliveries(delivery_id TEXT PRIMARY KEY, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS project_settings(project_slug TEXT PRIMARY KEY, auto_accept INTEGER NOT NULL DEFAULT 1, auto_accept_require_checklist INTEGER NOT NULL DEFAULT 0, required_checks TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS ci_checks(project_slug TEXT NOT NULL, sha TEXT NOT NULL, kind TEXT NOT NULL, run_id TEXT NOT NULL, state TEXT NOT NULL, updated REAL NOT NULL, PRIMARY KEY(project_slug,sha,kind,run_id));"""),
)


def migrate(conn, webhook=False):
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_versions(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)")
        versions = {r[0] for r in conn.execute("SELECT version FROM schema_versions")}
        supported = {v for v, _ in MIGRATIONS}
        if versions - supported or versions != set(range(1, max(versions, default=0) + 1)):
            raise RuntimeError("unsupported or non-sequential schema version")
        for version, script in MIGRATIONS:
            if version == 3 and not webhook:
                continue
            if version in versions:
                continue
            if version != len(versions) + 1:
                raise RuntimeError("non-sequential schema migration")
            # sqlite executescript() commits transactions: execute statements individually.
            for statement in script.split(";"):
                if statement.strip():
                    if version == 3 and statement.strip().startswith("ALTER TABLE projects") and "branch" in [r[1] for r in conn.execute("PRAGMA table_info(projects)")]:
                        continue
                    conn.execute(statement)
            conn.execute("INSERT INTO schema_versions(version,applied_at) VALUES(?,?)", (version, time.time()))
            versions.add(version)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def check_health(conn):
    try:
        return conn.execute("SELECT 1").fetchone()[0] == 1
    except Exception:
        return False


# Explicit allowlist: never persist arbitrary payloads, passwords, tokens or notes.
AUDIT_FIELDS = {
    "login": ("ip",), "login.failure": ("ip",), "login.locked": ("ip",), "login.rate_limited": ("ip",),
    "password.change": (), "sessions.revoke": (),
    "project.create": ("slug",), "plan.import": ("slug", "packages"),
    "task.auto_accept": ("slug", "id", "sha"),
    "plan.sync": ("slug",), "task.status": ("slug", "id", "status"),
}
SAFE_IDENT = re.compile(r"^[a-zA-Z0-9_.:-]{1,80}$")


def recent_audit(conn, limit=200):
    output = []
    for row in conn.execute("SELECT id,ts,action,payload FROM audit ORDER BY id DESC LIMIT ?", (min(max(int(limit), 0), 200),)):
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        allowed = AUDIT_FIELDS.get(row["action"], ())
        sanitized = {k: v for k, v in payload.items() if k in allowed and
                     ((isinstance(v, str) and SAFE_IDENT.fullmatch(v)) or
                      (type(v) is int and 0 <= v <= 1_000_000))}
        output.append({"id": row["id"], "ts": row["ts"], "action": row["action"], "payload": sanitized})
    return output


def connect(path, webhook=False):
    conn = sqlite3.connect(path, isolation_level=None, timeout=10, check_same_thread=False)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        migrate(conn, webhook=webhook)
        return conn
    except Exception:
        conn.close()
        raise


def audit(conn, action, payload=None):
    allowed = AUDIT_FIELDS.get(action, ())
    value = payload if isinstance(payload, dict) else {}
    safe = {k: v for k, v in value.items() if k in allowed and
            ((isinstance(v, str) and SAFE_IDENT.fullmatch(v)) or
             (type(v) is int and 0 <= v <= 1_000_000))}
    conn.execute("INSERT INTO audit(ts,action,payload) VALUES(?,?,?)", (time.time(), action, json.dumps(safe, ensure_ascii=False)))
