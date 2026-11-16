"""A1 regression and security contract tests, isolated SQLite only."""
import io
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from portal import auth, db
from portal.app import create_app
from portal.tests.test_portal import PW, call

BASE = '/createportal'
NEW = 'a-long-new-password-2026'


class A1Security(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'portal.sqlite')
        c = db.connect(self.path)
        auth.set_password(c, 'owner', PW)
        c.close()
        self.app = create_app(self.path, base=BASE, secure_cookie=True, security_v2=True)

    def tearDown(self):
        self.app.close()
        self.tmp.cleanup()

    def req(self, method, path, body=None, cookie='', csrf='', ip='127.0.0.1'):
        return call(self.app, method, BASE + path, body, cookie, csrf, ip)

    def login(self, password=PW, ip='127.0.0.1'):
        r = self.req('POST', '/api/login', {'username': 'owner', 'password': password}, ip=ip)
        self.assertEqual(r['status'], 200, r)
        return r['headers']['Set-Cookie'].split(';')[0], r['json']['csrf']

    def change(self, cookie, csrf, old=PW, new=NEW):
        return self.req('POST', '/api/password', {'current_password': old, 'new_password': new}, cookie, csrf)

    def test_password_unauthorized(self):
        self.assertEqual(self.change('', '')['status'], 401)

    def test_password_csrf_absent(self):
        c, csrf = self.login()
        self.assertEqual(self.change(c, '')['status'], 403)

    def test_password_csrf_wrong(self):
        c, csrf = self.login()
        self.assertEqual(self.change(c, 'wrong')['status'], 403)

    def test_password_wrong_current(self):
        c, csrf = self.login()
        self.assertEqual(self.change(c, csrf, 'wrong-password')['status'], 401)
        self.assertEqual(self.req('GET', '/api/me', cookie=c)['status'], 200)

    def test_password_short(self):
        c, csrf = self.login()
        self.assertEqual(self.change(c, csrf, new='x' * 13)['status'], 400)

    def test_password_exactly_14(self):
        c, csrf = self.login()
        self.assertEqual(self.change(c, csrf, new='x' * 14)['status'], 200)

    def test_password_reuse(self):
        c, csrf = self.login()
        self.assertEqual(self.change(c, csrf, new=PW)['status'], 400)

    def test_password_repeated_current_rejected(self):
        c, csrf = self.login()
        first = self.change(c, csrf)
        self.assertEqual(first['status'], 200)
        self.assertEqual(self.change(c, first['json']['csrf'])['status'], 401)

    def test_password_new_login_and_old_rejected(self):
        c, csrf = self.login()
        self.assertEqual(self.change(c, csrf)['status'], 200)
        self.assertEqual(self.req('POST', '/api/login', {'username': 'owner', 'password': PW}, ip='1.1.1.1')['status'], 401)
        self.login(NEW, ip='2.2.2.2')

    def test_password_other_session_revoked(self):
        c, csrf = self.login()
        other, _ = self.login(ip='1.2.3.4')
        self.assertEqual(self.change(c, csrf)['status'], 200)
        self.assertEqual(self.req('GET', '/api/me', cookie=other)['status'], 401)
        self.assertEqual(self.req('GET', '/api/me', cookie=c)['status'], 200)

    def test_password_rotates_csrf(self):
        c, csrf = self.login()
        changed = self.change(c, csrf)
        self.assertEqual(changed['status'], 200)
        self.assertNotEqual(csrf, changed['json']['csrf'])
        self.assertEqual(self.change(c, csrf, NEW, 'yet-another-password')['status'], 403)

    def test_password_no_secret_in_response_or_audit(self):
        c, csrf = self.login()
        r = self.change(c, csrf)
        a = self.req('GET', '/api/audit', cookie=c)
        for raw in (r['body'], a['body']):
            self.assertNotIn(PW.encode(), raw)
            self.assertNotIn(NEW.encode(), raw)
        self.assertIn('password.change', [x['action'] for x in a['json']['entries']])

    def test_password_wrong_type(self):
        c, csrf = self.login()
        self.assertEqual(self.req('POST', '/api/password', {'current_password': {}, 'new_password': NEW}, c, csrf)['status'], 400)

    def test_password_unknown_field(self):
        c, csrf = self.login()
        self.assertEqual(self.req('POST', '/api/password', {'current_password': PW, 'new_password': NEW, 'extra': 1}, c, csrf)['status'], 400)

    def test_revoke_requires_session(self):
        self.assertEqual(self.req('POST', '/api/sessions/revoke', {'current_password': PW})['status'], 401)

    def test_revoke_requires_csrf(self):
        c, _ = self.login()
        self.assertEqual(self.req('POST', '/api/sessions/revoke', {'current_password': PW}, c)['status'], 403)

    def test_revoke_wrong_password(self):
        c, csrf = self.login()
        self.assertEqual(self.req('POST', '/api/sessions/revoke', {'current_password': 'bad'}, c, csrf)['status'], 401)
        self.assertEqual(self.req('GET', '/api/me', cookie=c)['status'], 200)

    def test_revoke_all_including_current_and_repeat(self):
        c, csrf = self.login()
        other, _ = self.login(ip='8.8.8.8')
        r = self.req('POST', '/api/sessions/revoke', {'current_password': PW}, c, csrf)
        self.assertEqual(r['status'], 200)
        self.assertIn('Max-Age=0', r['headers']['Set-Cookie'])
        self.assertEqual(self.req('GET', '/api/me', cookie=c)['status'], 401)
        self.assertEqual(self.req('GET', '/api/me', cookie=other)['status'], 401)
        self.assertEqual(self.req('POST', '/api/sessions/revoke', {'current_password': PW}, c, csrf)['status'], 401)

    def test_revoke_wrong_types(self):
        c, csrf = self.login()
        for body in ({}, {'current_password': 123}, {'current_password': PW, 'junk': NEW}):
            self.assertEqual(self.req('POST', '/api/sessions/revoke', body, c, csrf)['status'], 400)

    def test_audit_requires_session(self):
        self.assertEqual(self.req('GET', '/api/audit')['status'], 401)

    def test_audit_last_200_descending(self):
        c, _ = self.login()
        conn = db.connect(self.path)
        for i in range(210):
            db.audit(conn, 'plan.import', {'slug': 'safe', 'packages': i})
        conn.close()
        entries = self.req('GET', '/api/audit', cookie=c)['json']['entries']
        self.assertEqual(len(entries), 200)
        self.assertEqual(entries[0]['payload']['packages'], 209)
        self.assertEqual(entries[-1]['payload']['packages'], 10)

    def test_audit_filters_legacy_secret_payloads(self):
        c, _ = self.login()
        conn = db.connect(self.path)
        conn.execute('INSERT INTO audit(ts,action,payload) VALUES(?,?,?)', (time.time(), 'login', json.dumps({'ip': '127.0.0.1', 'password': PW, 'token': NEW})))
        conn.close()
        result = self.req('GET', '/api/audit', cookie=c)
        self.assertNotIn(PW.encode(), result['body'])
        self.assertNotIn(NEW.encode(), result['body'])
        self.assertEqual(result['json']['entries'][0]['payload'], {'ip': '127.0.0.1'})

    def test_audit_unknown_action_payload_empty(self):
        c, _ = self.login()
        conn = db.connect(self.path)
        db.audit(conn, 'arbitrary', {'token': NEW})
        conn.close()
        self.assertEqual(self.req('GET', '/api/audit', cookie=c)['json']['entries'][0]['payload'], {})

    def test_login_success_and_failure_audit(self):
        self.login()
        self.req('POST', '/api/login', {'username': 'owner', 'password': 'bad'}, ip='1.2.3.4')
        c, _ = self.login(ip='2.3.4.5')
        actions = [x['action'] for x in self.req('GET', '/api/audit', cookie=c)['json']['entries']]
        self.assertIn('login', actions)
        self.assertIn('login.failure', actions)

    def test_hourly_lock_after_20(self):
        conn = db.connect(self.path)
        for i in range(19):
            auth.note_attempt(conn, '4.4.4.4')
        conn.close()
        self.assertEqual(self.req('POST', '/api/login', {'username': 'owner', 'password': 'bad'}, ip='4.4.4.4')['status'], 429)
        self.assertEqual(self.req('POST', '/api/login', {'username': 'owner', 'password': PW}, ip='4.4.4.4')['status'], 429)
        c, _ = self.login(ip='5.5.5.5')
        actions = [x['action'] for x in self.req('GET', '/api/audit', cookie=c)['json']['entries']]
        self.assertIn('login', actions)

    def test_hourly_window_pruning(self):
        conn = db.connect(self.path)
        for i in range(20):
            auth.note_attempt(conn, '7.7.7.7', now=time.time()-3700)
        self.assertFalse(auth.hourly_locked(conn, '7.7.7.7'))
        conn.close()
        self.login(ip='7.7.7.7')

    def test_migrations_repeat_no_change(self):
        c = db.connect(self.path)
        v = list(c.execute('SELECT version,applied_at FROM schema_versions ORDER BY version'))
        c.close()
        c = db.connect(self.path)
        self.assertEqual([tuple(x) for x in v], [tuple(x) for x in c.execute('SELECT version,applied_at FROM schema_versions ORDER BY version')])
        c.close()

    def test_migration_legacy_data_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'legacy.sqlite')
            c = sqlite3.connect(path)
            c.executescript(db.SCHEMA)
            c.execute('INSERT INTO projects(slug,name,created) VALUES(?,?,?)', ('legacy-project', 'Old', 1.0))
            c.commit()
            c.close()
            c = db.connect(path)
            self.assertEqual(c.execute("SELECT name FROM projects WHERE slug='legacy-project'").fetchone()[0], 'Old')
            self.assertEqual([x[0] for x in c.execute('SELECT version FROM schema_versions ORDER BY version')], [1, 2])
            c.close()

    def test_migration_future_version_rejected(self):
        c = db.connect(self.path)
        c.execute('INSERT INTO schema_versions(version,applied_at) VALUES(?,?)', (99, time.time()))
        c.close()
        with self.assertRaises(RuntimeError):
            db.connect(self.path)

    def test_migration_gap_rejected(self):
        c = db.connect(self.path)
        c.execute('DELETE FROM schema_versions WHERE version=1')
        c.close()
        with self.assertRaises(RuntimeError):
            db.connect(self.path)

    def test_health_db_check(self):
        self.assertEqual(self.req('GET', '/health')['json'], {'ok': True})
        with patch('portal.db.check_health', return_value=False):
            self.assertEqual(self.req('GET', '/health')['status'], 503)

    def test_existing_plan_and_sync_audit(self):
        c, csrf = self.login()
        from portal import bootstrap
        self.assertEqual(self.req('POST', '/api/projects', {'slug': 'demo-project', 'name': 'demo', 'repo': 'owner/repo'}, c, csrf)['status'], 201)
        self.assertEqual(self.req('POST', '/api/projects/demo-project/plan', {'plan': bootstrap.STARTER_PLAN}, c, csrf)['status'], 200)
        a = self.req('GET', '/api/audit', cookie=c)['json']['entries']
        self.assertIn('plan.import', [e['action'] for e in a])

    def test_password_oversized_rejected(self):
        c, csrf = self.login()
        self.assertEqual(self.change(c, csrf, new='A' * 301)['status'], 400)

    def test_password_empty_current_rejected(self):
        c, csrf = self.login()
        self.assertEqual(self.change(c, csrf, old='')['status'], 400)

    def test_revoke_cleared_cookie_secure(self):
        c, csrf = self.login()
        r = self.req('POST', '/api/sessions/revoke', {'current_password': PW}, c, csrf)
        self.assertIn('Secure', r['headers']['Set-Cookie'])
        self.assertIn('HttpOnly', r['headers']['Set-Cookie'])

    def test_audit_login_success_not_echo_password(self):
        c, _ = self.login()
        data = self.req('GET', '/api/audit', cookie=c)['body']
        self.assertNotIn(PW.encode(), data)
        self.assertNotIn(b'csrf', data)

    def test_login_rejects_nonstring_password(self):
        r = self.req('POST', '/api/login', {'username': 'owner', 'password': ['x']}, ip='9.2.1.3')
        self.assertEqual(r['status'], 400)

    def test_audit_no_passwords_in_database_log(self):
        c, csrf = self.login()
        self.change(c, csrf)
        conn = db.connect(self.path)
        contents = '\n'.join(x[0] for x in conn.execute('SELECT payload FROM audit'))
        self.assertNotIn(PW, contents)
        self.assertNotIn(NEW, contents)
        conn.close()

    def test_security_can_be_disabled_explicitly(self):
        legacy = create_app(self.path, base=BASE, security_v2=False)
        try:
            cookie, csrf = self.login(ip='20.0.0.1')
            self.assertEqual(call(legacy, 'GET', BASE + '/api/audit', cookie=cookie)['status'], 404)
            self.assertEqual(call(legacy, 'POST', BASE + '/api/password', {'current_password': PW, 'new_password': NEW}, cookie, csrf)['status'], 404)
            self.assertEqual(call(legacy, 'POST', BASE + '/api/sessions/revoke', {'current_password': PW}, cookie, csrf)['status'], 404)
        finally:
            legacy.close()

    def test_security_enabled_by_default(self):
        default = create_app(self.path, base=BASE)
        try:
            cookie, _ = self.login(ip='20.0.0.2')
            self.assertEqual(call(default, 'GET', BASE + '/api/audit', cookie=cookie)['status'], 200)
        finally:
            default.close()

    def test_real_ip_trusted_only_from_loopback_proxy(self):
        def attempt(remote, real):
            raw = json.dumps({'username': 'owner', 'password': 'wrong-password-123'}).encode()
            res = {}
            def st(status, headers):
                res['status'] = int(status.split()[0])
            env = {'REQUEST_METHOD': 'POST', 'PATH_INFO': BASE + '/api/login', 'CONTENT_LENGTH': str(len(raw)), 'wsgi.input': io.BytesIO(raw),
                   'REMOTE_ADDR': remote, 'HTTP_X_REAL_IP': real}
            b''.join(self.app(env, st))
            return res['status']
        # за прокси разные клиенты считаются раздельно
        for _ in range(auth.ATTEMPT_LIMIT):
            self.assertEqual(attempt('127.0.0.1', '5.5.5.5'), 401)
        self.assertEqual(attempt('127.0.0.1', '5.5.5.5'), 429)
        self.assertEqual(attempt('127.0.0.1', '6.6.6.6'), 401)
        # прямой клиент не может подменить адрес заголовком
        for _ in range(auth.ATTEMPT_LIMIT):
            attempt('8.8.8.8', '9.9.9.1')
        self.assertEqual(attempt('8.8.8.8', '9.9.9.2'), 429)

    def test_rate_limit_audit(self):
        conn = db.connect(self.path)
        for _ in range(auth.ATTEMPT_LIMIT):
            auth.note_attempt(conn, '10.10.10.10')
        conn.close()
        self.assertEqual(self.req('POST', '/api/login', {'username': 'owner', 'password': PW}, ip='10.10.10.10')['status'], 429)
        c, _ = self.login(ip='10.10.10.11')
        actions = [x['action'] for x in self.req('GET', '/api/audit', cookie=c)['json']['entries']]
        self.assertIn('login.rate_limited', actions)

    def test_audit_ip_and_project_identifiers_only(self):
        c, _ = self.login()
        conn = db.connect(self.path)
        db.audit(conn, 'plan.sync', {'slug': 'demo-project', 'private_key': 'horrible'})
        conn.close()
        entry = self.req('GET', '/api/audit', cookie=c)['json']['entries'][0]
        self.assertEqual(entry['payload'], {'slug': 'demo-project'})

    def test_revoke_audit(self):
        c, csrf = self.login()
        self.req('POST', '/api/sessions/revoke', {'current_password': PW}, c, csrf)
        c, _ = self.login(ip='6.6.6.6')
        actions = [x['action'] for x in self.req('GET', '/api/audit', cookie=c)['json']['entries']]
        self.assertIn('sessions.revoke', actions)
