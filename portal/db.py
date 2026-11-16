"""SQLite-хранилище портала. Один владелец, несколько проектов."""
from __future__ import annotations

import json
import sqlite3
import time

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
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, ts REAL NOT NULL, action TEXT NOT NULL, payload TEXT NOT NULL);
"""


def connect(path):
    conn = sqlite3.connect(path, isolation_level=None, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


def audit(conn, action, payload=None):
    conn.execute("INSERT INTO audit(ts,action,payload) VALUES(?,?,?)", (time.time(), action, json.dumps(payload or {}, ensure_ascii=False)))
