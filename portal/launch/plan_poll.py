"""A6 optional, rate-limited background refresh for a project's configured plan path.

Off unless PORTAL_LAUNCH_ENABLED=1. No secrets or plan bodies enter logs.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from portal.launch import valid_plan_path
from portal.backup.sync import read_token
from tools import work_plan as wp

REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MAX_PLAN_BYTES = 900_000


def fetch_text(url, token):
    if not url.startswith("https://api.github.com/repos/"):
        raise ValueError("invalid_github_url")
    headers = {"User-Agent": "CreatePortal-A6", "Accept": "application/vnd.github.raw+json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=10) as response:
        raw = response.read(MAX_PLAN_BYTES + 1)
    if len(raw) > MAX_PLAN_BYTES:
        raise ValueError("plan_too_large")
    return raw.decode("utf-8")


def poll_plans(conn, token_file=None, *, now=None, fetch=None, max_projects=10):
    """Retrieve only due projects, using *each project's* plan_path.

    GitHub failures are non-destructive and retried on the next configured interval.
    """
    now = time.time() if now is None else now
    fetch = fetch or fetch_text
    token = ""
    try:
        token = read_token(token_file)
    except (OSError, ValueError):
        # Public repos work without a token; private repo refresh simply fails closed.
        pass
    rows = conn.execute("""SELECT p.slug,p.repo,p.plan_path,p.poll_minutes,p.plan_json,
       COALESCE(s.last_checked,0) AS last_checked
       FROM projects p LEFT JOIN project_plan_poll s ON s.project_slug=p.slug
       WHERE p.sync_mode IN ('polling','both') AND p.repo<>''
       ORDER BY last_checked,p.slug""").fetchall()
    count = 0
    for row in rows:
        if count >= max_projects:
            break
        minutes = row["poll_minutes"] if row["poll_minutes"] in (5,10,30) else 5
        if now - row["last_checked"] < minutes * 60:
            continue
        if not REPO.fullmatch(row["repo"]) or not valid_plan_path(row["plan_path"]):
            continue
        count += 1
        state = "error"
        try:
            url = f'https://api.github.com/repos/{row["repo"]}/contents/{row["plan_path"]}'
            data = fetch(url, token)
            if not isinstance(data, str) or len(data.encode('utf-8')) > MAX_PLAN_BYTES:
                raise ValueError("invalid_plan_response")
            plan = json.loads(data)
            if not isinstance(plan, dict) or wp.validate(plan):
                raise ValueError("invalid_plan")
            # No write to project data when content is unchanged; never wipe an old plan.
            serialized = json.dumps(plan, ensure_ascii=False)
            if row["plan_json"] is None or json.loads(row["plan_json"]) != plan:
                conn.execute("UPDATE projects SET plan_json=?,plan_updated=? WHERE slug=?", (serialized, now, row["slug"]))
            state = "ok"
        except (OSError, ValueError, TypeError, KeyError, UnicodeError):
            pass
        conn.execute("""INSERT INTO project_plan_poll(project_slug,last_checked,last_state) VALUES(?,?,?)
                      ON CONFLICT(project_slug) DO UPDATE SET last_checked=excluded.last_checked,last_state=excluded.last_state""",
                     (row["slug"], now, state))
    return count
