"""GitHub webhook processing with atomic delivery deduplication and CI-gated acceptance."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time

from portal import db
from tools import work_plan as wp

DELIVERY = re.compile(r'^[A-Za-z0-9-]{8,100}$')
SHA = re.compile(r'^[0-9a-f]{40}$')
BRANCH_ID = re.compile(r'^[A-Za-z0-9._/-]{1,180}$')


def verified(raw, signature, secret):
    if not isinstance(signature, str) or not signature.startswith('sha256=') or len(signature) != 71:
        return False
    return hmac.compare_digest(signature, 'sha256=' + hmac.new(secret, raw, hashlib.sha256).hexdigest())


def event(conn, slug, pkg, kind, source='github', **fields):
    # Event metadata is built by this module from allowlisted values only.
    conn.execute('INSERT INTO events(project_slug,pkg_id,ts,kind,source,payload) VALUES(?,?,?,?,?,?)',
                 (slug, pkg, time.time(), kind, source, json.dumps(fields, ensure_ascii=False)))


def settings(conn, slug):
    row = conn.execute('SELECT * FROM project_settings WHERE project_slug=?', (slug,)).fetchone()
    return {'auto_accept': bool(row['auto_accept']) if row else True,
            'auto_accept_require_checklist': bool(row['auto_accept_require_checklist']) if row else False,
            'required_checks': json.loads(row['required_checks']) if row else []}


def task_id(plan, branch, title):
    ids = {p['id'] for p in plan.get('packages', []) if isinstance(p, dict) and isinstance(p.get('id'), str)}
    match = re.match(r'^[a-zA-Z0-9_-]+/([A-Za-z][A-Za-z0-9_]*)(?:-|$)', branch)
    if match and match.group(1) in ids:
        return match.group(1)
    for candidate in sorted(ids, key=len, reverse=True):
        if re.search(r'(?<![A-Za-z0-9])' + re.escape(candidate) + r'(?![A-Za-z0-9])', title, re.I):
            return candidate
    return None


def ci_status(conn, slug, sha, required):
    checks = list(conn.execute('SELECT kind,run_id,state FROM ci_checks WHERE project_slug=? AND sha=?', (slug, sha)))
    if not checks:
        return 'pending'
    if any(r['state'] == 'failure' for r in checks):
        return 'failure'
    if any(r['state'] != 'success' for r in checks):
        return 'pending'
    if required and not all(any(r['run_id'] == name and r['state'] == 'success' for r in checks) for name in required):
        return 'pending'
    return 'success'


def reconcile(conn, slug):
    cfg = settings(conn, slug)
    project = conn.execute('SELECT branch FROM projects WHERE slug=?', (slug,)).fetchone()
    if not project:
        return
    for pr in conn.execute("SELECT * FROM pr_links WHERE project_slug=? AND state='merged'", (slug,)).fetchall():
        if pr['base_branch'] != project['branch'] or not SHA.fullmatch(pr['sha']):
            continue
        ci = ci_status(conn, slug, pr['sha'], cfg['required_checks'])
        conn.execute('UPDATE pr_links SET ci_state=?,updated=? WHERE project_slug=? AND pr_number=?',
                     (ci, time.time(), slug, pr['pr_number']))
        state = conn.execute('SELECT status FROM task_state WHERE project_slug=? AND pkg_id=?', (slug, pr['pkg_id'])).fetchone()
        if state and state['status'] == 'accepted':
            continue
        if ci != 'success':
            kind = 'ci.failed' if ci == 'failure' else 'ci.waiting'
            previous = conn.execute('SELECT kind,payload FROM events WHERE project_slug=? AND pkg_id=? ORDER BY id DESC LIMIT 1',
                                    (slug, pr['pkg_id'])).fetchone()
            marker = json.dumps({'sha': pr['sha']})
            if not previous or previous['kind'] != kind or previous['payload'] != marker:
                event(conn, slug, pr['pkg_id'], kind, sha=pr['sha'])
            continue
        if not cfg['auto_accept'] or cfg['auto_accept_require_checklist']:
            continue
        old = state['status'] if state else 'planned'
        if old not in ('planned', 'issued', 'submitted'):
            continue
        note = 'принято автоматически: слито в main, CI зелёный'
        if old == 'planned':
            note += '; без отметки выдачи'
        conn.execute('INSERT OR IGNORE INTO task_state(project_slug,pkg_id) VALUES(?,?)', (slug, pr['pkg_id']))
        conn.execute("UPDATE task_state SET status='accepted',merged=1,sha=?,accepted_at=?,note=? WHERE project_slug=? AND pkg_id=? AND status=?",
                     (pr['sha'], time.time(), note, slug, pr['pkg_id'], old))
        if conn.execute('SELECT changes()').fetchone()[0]:
            event(conn, slug, pr['pkg_id'], 'task.auto_accept', sha=pr['sha'], pr=pr['pr_number'])
            db.audit(conn, 'task.auto_accept', {'slug': slug, 'id': pr['pkg_id'], 'sha': pr['sha']})


def process(conn, kind, payload, delivery, fetch_plan=None):
    """Called only after HMAC verification; one transaction includes dedup and updates."""
    if not DELIVERY.fullmatch(delivery) or not isinstance(payload, dict):
        raise ValueError('invalid delivery')
    repo = payload.get('repository')
    full = repo.get('full_name') if isinstance(repo, dict) else None
    if not isinstance(full, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', full):
        raise ValueError('invalid repository')
    conn.execute('BEGIN IMMEDIATE')
    try:
        if conn.execute('SELECT 1 FROM webhook_deliveries WHERE delivery_id=?', (delivery,)).fetchone():
            conn.execute('COMMIT')
            return 'duplicate'
        conn.execute('INSERT INTO webhook_deliveries(delivery_id,ts) VALUES(?,?)', (delivery, time.time()))
        projects = conn.execute('SELECT * FROM projects WHERE repo=?', (full,)).fetchall()
        for project in projects:
            slug = project['slug']
            if kind == 'push':
                if payload.get('ref') != 'refs/heads/' + project['branch']:
                    continue
                try:
                    plan = json.loads(fetch_plan(full)) if fetch_plan else None
                    if not isinstance(plan, dict) or wp.validate(plan):
                        raise ValueError('invalid plan')
                except Exception:
                    event(conn, slug, None, 'plan.sync_failed')
                else:
                    conn.execute('UPDATE projects SET plan_json=?,plan_updated=? WHERE slug=?', (json.dumps(plan, ensure_ascii=False), time.time(), slug))
                    event(conn, slug, None, 'plan.synced')
            elif kind == 'pull_request':
                pr = payload.get('pull_request')
                if not isinstance(pr, dict) or type(payload.get('number')) is not int or not 1 <= payload['number'] <= 1_000_000_000:
                    raise ValueError('invalid PR')
                head, base = pr.get('head'), pr.get('base')
                if not isinstance(head, dict) or not isinstance(base, dict):
                    raise ValueError('invalid PR refs')
                branch, base_branch = head.get('ref'), base.get('ref')
                if not isinstance(branch, str) or not BRANCH_ID.fullmatch(branch) or not isinstance(base_branch, str) or not BRANCH_ID.fullmatch(base_branch):
                    raise ValueError('invalid branch')
                if not isinstance(head.get('repo'), dict) or not isinstance(base.get('repo'), dict):
                    continue
                if head['repo'].get('full_name') != full or base['repo'].get('full_name') != full:
                    continue
                plan = json.loads(project['plan_json']) if project['plan_json'] else {}
                pkg = task_id(plan, branch, pr.get('title') if isinstance(pr.get('title'), str) else '')
                if not pkg:
                    continue
                merged = pr.get('merged') is True and payload.get('action') == 'closed'
                sha = pr.get('merge_commit_sha') if merged else head.get('sha')
                if not isinstance(sha, str) or not SHA.fullmatch(sha):
                    sha = ''
                state = 'merged' if merged else ('closed' if payload.get('action') == 'closed' else 'open')
                conn.execute('INSERT INTO pr_links(project_slug,pkg_id,pr_number,branch,sha,state,updated,base_branch) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(project_slug,pr_number) DO UPDATE SET pkg_id=excluded.pkg_id,branch=excluded.branch,sha=excluded.sha,state=excluded.state,updated=excluded.updated,base_branch=excluded.base_branch',
                             (slug, pkg, payload['number'], branch, sha, state, time.time(), base_branch))
                if merged and base_branch == project['branch'] and sha:
                    conn.execute('INSERT OR IGNORE INTO task_state(project_slug,pkg_id) VALUES(?,?)', (slug, pkg))
                    conn.execute('UPDATE task_state SET merged=1,sha=? WHERE project_slug=? AND pkg_id=?', (sha, slug, pkg))
                event(conn, slug, pkg, 'pr.' + state, pr=payload['number'], sha=sha)
                reconcile(conn, slug)
            elif kind in ('check_suite', 'workflow_run'):
                run = payload.get(kind)
                if not isinstance(run, dict):
                    raise ValueError('invalid CI event')
                sha = run.get('head_sha')
                if not isinstance(sha, str) or not SHA.fullmatch(sha):
                    continue
                app = run.get('app')
                run_id = run.get('name') if kind == 'workflow_run' else (app.get('slug', 'check_suite') if isinstance(app, dict) else 'check_suite')
                if not isinstance(run_id, str) or not 1 <= len(run_id) <= 100:
                    continue
                status = run.get('status')
                conclusion = run.get('conclusion')
                state = 'pending' if status != 'completed' else ('success' if conclusion == 'success' else 'failure')
                conn.execute('INSERT INTO ci_checks(project_slug,sha,kind,run_id,state,updated) VALUES(?,?,?,?,?,?) ON CONFLICT(project_slug,sha,kind,run_id) DO UPDATE SET state=excluded.state,updated=excluded.updated',
                             (slug, sha, kind, run_id, state, time.time()))
                reconcile(conn, slug)
        conn.execute('COMMIT')
        return 'processed'
    except Exception:
        conn.execute('ROLLBACK')
        raise
