"""Резервные копии, экспорт/импорт проекта, удаление и граф зависимостей. Чистые функции без HTTP: маршруты подключает A5."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
FORMAT = "createportal-project-1"
# Таблицы со столбцом project_slug, которые принадлежат проекту (порядок важен только для вставки: связей FK нет).
PROJECT_TABLES = ("task_state", "ideas", "start_state", "events", "pr_links", "project_settings", "ci_checks", "task_reports", "task_reviews")
MAX_IMPORT_ROWS = 50000


class BackupError(Exception):
    pass


# ---------- резервные копии ----------

def create_backup(db_path, dest_dir, keep=14, now=None):
    """Копия через sqlite backup API (безопасна при работающем сервисе). Возвращает путь. Старые сверх keep удаляются."""
    os.makedirs(dest_dir, mode=0o700, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(now if now is not None else time.time()))
    path = os.path.join(dest_dir, f"portal-{stamp}.sqlite")
    n = 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(dest_dir, f"portal-{stamp}-{n}.sqlite")
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.chmod(path, 0o600)
    if not verify_backup(path)["ok"]:
        os.remove(path)
        raise BackupError("backup failed integrity check")
    prune(dest_dir, keep)
    return path


def list_backups(dest_dir):
    if not os.path.isdir(dest_dir):
        return []
    out = []
    for name in sorted(os.listdir(dest_dir), reverse=True):
        if re.fullmatch(r"portal-\d{8}-\d{6}(-\d+)?\.sqlite", name):
            st = os.stat(os.path.join(dest_dir, name))
            out.append({"name": name, "size": st.st_size, "mtime": st.st_mtime})
    return out


def prune(dest_dir, keep=14):
    for item in list_backups(dest_dir)[max(int(keep), 1):]:
        os.remove(os.path.join(dest_dir, item["name"]))


def verify_backup(path):
    """Открывает копию только для чтения: целостность, число проектов и пользователей. Ничего не пишет."""
    try:
        c = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        try:
            integrity = c.execute("PRAGMA integrity_check").fetchone()[0]
            projects = c.execute("SELECT count(*) FROM projects").fetchone()[0]
            users = c.execute("SELECT count(*) FROM users").fetchone()[0]
        finally:
            c.close()
        return {"ok": integrity == "ok", "integrity": integrity, "projects": projects, "users": users}
    except sqlite3.Error as e:
        return {"ok": False, "integrity": str(e)[:100], "projects": 0, "users": 0}


def latest_backup(dest_dir):
    items = list_backups(dest_dir)
    return os.path.join(dest_dir, items[0]["name"]) if items else None


def restore_backup(backup_path, target_path):
    """Восстановление в НОВЫЙ файл (существующий не перезаписывается). Применять к остановленному сервису вручную."""
    if os.path.exists(target_path):
        raise BackupError("target exists")
    if not verify_backup(backup_path)["ok"]:
        raise BackupError("backup is not valid")
    src = sqlite3.connect("file:%s?mode=ro" % backup_path, uri=True)
    dst = sqlite3.connect(target_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.chmod(target_path, 0o600)
    return target_path


# ---------- экспорт / импорт / удаление ----------

def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _cols(conn, table):
    return [r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)]


def export_project(conn, slug):
    """JSON-совместимый словарь: проект, план и все его данные. Без пользователей, паролей, сессий и журнала входов."""
    row = conn.execute("SELECT * FROM projects WHERE slug=?", (slug,)).fetchone()
    if row is None:
        raise BackupError("project not found")
    have = _tables(conn)
    data = {"format": FORMAT, "exported": time.time(), "project": {k: row[k] for k in row.keys()}, "tables": {}}
    for t in PROJECT_TABLES:
        if t in have:
            cols = _cols(conn, t)
            data["tables"][t] = [dict(zip(cols, r)) for r in conn.execute("SELECT %s FROM %s WHERE project_slug=?" % (",".join(cols), t), (slug,))]
    return data


def _check_import(data):
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise BackupError("unknown format")
    project = data.get("project")
    tables = data.get("tables")
    if not isinstance(project, dict) or not isinstance(tables, dict):
        raise BackupError("bad structure")
    if not isinstance(project.get("slug"), str) or not SLUG.match(project["slug"]):
        raise BackupError("bad slug")
    if not isinstance(project.get("name"), str) or not project["name"]:
        raise BackupError("bad name")
    total = 0
    for t, rows in tables.items():
        if t not in PROJECT_TABLES or not isinstance(rows, list):
            raise BackupError("unexpected table")
        total += len(rows)
        for r in rows:
            if not isinstance(r, dict) or any(not isinstance(k, str) for k in r):
                raise BackupError("bad row")
    if total > MAX_IMPORT_ROWS:
        raise BackupError("too many rows")


def import_project(conn, data, new_slug=None):
    """Создаёт проект из экспорта. Существующий проект не перезаписывается (нужен другой slug). Всё в одной транзакции."""
    _check_import(data)
    project = dict(data["project"])
    slug = new_slug or project["slug"]
    if not SLUG.match(slug):
        raise BackupError("bad slug")
    if conn.execute("SELECT 1 FROM projects WHERE slug=?", (slug,)).fetchone():
        raise BackupError("project exists")
    have = _tables(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        pcols = [c for c in _cols(conn, "projects") if c in project]
        project["slug"] = slug
        conn.execute("INSERT INTO projects(%s) VALUES(%s)" % (",".join(pcols), ",".join("?" * len(pcols))), [project[c] for c in pcols])
        for t, rows in data["tables"].items():
            if t not in have:
                continue
            known = set(_cols(conn, t))
            for r in rows:
                r = dict(r)
                r["project_slug"] = slug
                if t == "ideas":
                    r.pop("id", None)  # новые идентификаторы, чтобы не столкнуться с чужими
                if t == "events":
                    r.pop("id", None)
                cols = [c for c in r if c in known]
                conn.execute("INSERT OR REPLACE INTO %s(%s) VALUES(%s)" % (t, ",".join(cols), ",".join("?" * len(cols))), [r[c] for c in cols])
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return slug


def delete_project(conn, slug, confirm):
    """Удаление только если confirm == slug. Возвращает число удалённых строк по таблицам."""
    if confirm != slug:
        raise BackupError("confirmation does not match")
    if not conn.execute("SELECT 1 FROM projects WHERE slug=?", (slug,)).fetchone():
        raise BackupError("project not found")
    have = _tables(conn)
    removed = {}
    conn.execute("BEGIN IMMEDIATE")
    try:
        for t in PROJECT_TABLES:
            if t in have:
                removed[t] = conn.execute("DELETE FROM %s WHERE project_slug=?" % t, (slug,)).rowcount
        conn.execute("DELETE FROM projects WHERE slug=?", (slug,))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return removed


# ---------- граф зависимостей ----------

def graph(plan, statuses=None):
    """Узлы, связи и критический путь (самая длинная цепочка зависимостей среди ещё не принятых пакетов, а если всё принято, среди всех)."""
    statuses = statuses or {}
    pkgs = {p["id"]: p for p in plan.get("packages", []) if isinstance(p, dict) and "id" in p}
    nodes = [{"id": i, "title": p.get("title", ""), "lane": p.get("lane", ""), "step": p.get("step", 0), "status": statuses.get(i, p.get("status", "planned"))}
             for i, p in pkgs.items()]
    edges = [{"from": d, "to": i} for i, p in pkgs.items() for d in p.get("depends_on", []) if d in pkgs]
    active = {i for i in pkgs if nodes_status(nodes, i) != "accepted"} or set(pkgs)
    memo = {}

    def longest(i, stack=()):
        if i in memo:
            return memo[i]
        if i in stack:
            raise BackupError("dependency cycle at %s" % i)
        best = []
        for d in pkgs[i].get("depends_on", []):
            if d in active and d in pkgs:
                cand = longest(d, stack + (i,))
                if len(cand) > len(best):
                    best = cand
        memo[i] = best + [i]
        return memo[i]

    path = []
    for i in sorted(active):
        cand = longest(i)
        if len(cand) > len(path):
            path = cand
    return {"nodes": nodes, "edges": edges, "critical_path": path}


def nodes_status(nodes, pid):
    for n in nodes:
        if n["id"] == pid:
            return n["status"]
    return "planned"
