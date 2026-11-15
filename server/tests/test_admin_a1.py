"""V2-ADM1 PostgreSQL integration and static contract tests."""
import io
import json
import os
import re
import unittest
from unittest.mock import patch
from pathlib import Path
from uuid import uuid4

from server import db
from server.game_server import create_app
from server.platform.security import hash_password, token_hash

DSN = os.getenv('LUNEX_TEST_DATABASE_URL')


def request(app, method, path, payload=None, token='', admin_token='', ip='10.77.0.1', query='', host='localhost:18777', forwarded=''):
    raw = json.dumps(payload or {}, ensure_ascii=False).encode()
    result = {}
    def start(status, headers):
        result['status'] = int(status.split()[0])
        result['headers'] = dict(headers)
    env = {
        'REQUEST_METHOD': method,
        'PATH_INFO': path,
        'QUERY_STRING': query,
        'CONTENT_LENGTH': str(len(raw)),
        'wsgi.input': io.BytesIO(raw),
        'REMOTE_ADDR': ip,
        'HTTP_HOST': host,
        'HTTP_AUTHORIZATION': 'Bearer ' + token if token else '',
        'HTTP_X_ADMIN_TOKEN': admin_token,
    }
    if forwarded:
        env['HTTP_X_FORWARDED_FOR'] = forwarded
    result['body'] = json.loads(b''.join(app(env, start)) or b'{}')
    return result


class TestAdminA1StaticContract(unittest.TestCase):
    def test_panel_is_self_contained_and_russian(self):
        root = Path(__file__).resolve().parents[2] / 'web' / 'admin'
        html = (root / 'index.html').read_text()
        js = (root / 'app.js').read_text()
        css = (root / 'styles.css').read_text()
        self.assertIn('lang="ru"', html)
        self.assertIn('./styles.css', html)
        self.assertIn('./config.js', html)
        self.assertNotIn('http://', html + js + css)
        self.assertNotIn('https://', html + js + css)
        self.assertIn('sessionStorage', js)
        self.assertGreater(len(js.splitlines()), 20)

    def test_roles_and_migration_contract(self):
        migration = (Path(__file__).resolve().parents[1] / 'migrations' / '202611160010_admin_a1.sql').read_text()
        for token in ('admin_sessions', 'actor_role', 'target_account_id', 'blocked_until'):
            self.assertIn(token, migration)


@unittest.skipUnless(DSN, 'Set LUNEX_TEST_DATABASE_URL to an isolated PostgreSQL database')
class AdminDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(DSN)

    @classmethod
    def tearDownClass(cls):
        cls.app.close()

    def account(self, role='owner', password='AdminPasswordLong!123'):
        suffix = uuid4().hex[:12]
        username = 'a' + suffix
        email = username + '@example.com'
        reg = request(self.app, 'POST', '/auth/register', {
            'username': username, 'email': email, 'password': password,
        }, ip='10.77.' + str(int(suffix[:2], 16) % 240 + 1) + '.3')
        self.assertEqual(reg['status'], 201, reg)
        with db.connect(DSN) as conn:
            conn.execute('UPDATE accounts SET role=%s WHERE id=%s', (role, reg['body']['id']))
            conn.commit()
        return reg['body']['id'], username, email, password

    def admin_login(self, username, password, ip='10.78.0.1'):
        result = request(self.app, 'POST', '/admin/login', {
            'username': username, 'password': password,
        }, ip=ip)
        self.assertEqual(result['status'], 200, result)
        return result['body']['token']

    def test_every_admin_route_requires_auth_and_loopback_rules_remain_403(self):
        routes = [
            ('GET', '/admin/overview', None), ('GET', '/admin/flags', None),
            ('GET', '/admin/settings', None), ('GET', '/admin/revisions', None),
            ('GET', '/admin/audit', None), ('GET', '/admin/players', None),
            ('GET', '/admin/players/1', None), ('GET', '/admin/world/growth', None),
            ('POST', '/admin/settings', {'key': 'registration_enabled', 'value': True}),
            ('POST', '/admin/sessions/revoke', {'player_id': 1}),
            ('POST', '/admin/roles', {'player_id': 1, 'role': 'viewer', 'confirm': True}),
        ]
        for method, path, body in routes:
            self.assertEqual(request(self.app, method, path, body, query='city=ufa')['status'], 403, path)
        secret = 'TEST_ONLY_ADMIN_ACCESS_TOKEN_123456789012345'
        self.assertEqual(request(self.app, 'GET', '/admin/overview', admin_token=secret, ip='10.1.2.3')['status'], 403)
        self.assertEqual(request(self.app, 'GET', '/admin/overview', admin_token='incorrect')['status'], 403)
        self.assertEqual(request(self.app, 'GET', '/admin/overview', admin_token=secret, host='rikagro.ru')['status'], 403)
        self.assertEqual(request(self.app, 'GET', '/admin/overview', admin_token=secret, forwarded='203.0.113.10')['status'], 403)
        with patch.dict(os.environ, {'LUNEX_ADMIN_TOKEN': secret}):
            self.assertEqual(request(self.app, 'GET', '/admin/overview', admin_token=secret)['status'], 200)

    def test_login_password_change_rate_limit_expiry_and_absolute_limit(self):
        account_id, username, _, password = self.account()
        self.assertEqual(request(self.app, 'POST', '/admin/login', {'username': username, 'password': password[:10]}, ip='10.79.0.1')['status'], 401)
        short_id, short_name, _, _ = self.account(password='ShortPass1')
        short = request(self.app, 'POST', '/admin/login', {'username': short_name, 'password': 'ShortPass1'}, ip='10.79.0.2')
        self.assertEqual(short['status'], 400)
        self.assertIn('14', short['body']['message'])
        for index in range(8):
            self.assertEqual(request(self.app, 'POST', '/admin/login', {'username': 'missing-' + uuid4().hex, 'password': 'wrong'}, ip='10.79.0.3')['status'], 401)
        self.assertEqual(request(self.app, 'POST', '/admin/login', {'username': 'last', 'password': 'wrong'}, ip='10.79.0.3')['status'], 429)
        token = self.admin_login(username, password, ip='10.79.0.4')
        changed = request(self.app, 'POST', '/admin/password', {'password': 'NewAdminPassword!456'}, token=token)
        self.assertEqual(changed['status'], 200, changed)
        self.assertEqual(request(self.app, 'POST', '/admin/logout', token=token)['status'], 200)
        new_token = self.admin_login(username, 'NewAdminPassword!456', ip='10.79.0.5')
        with db.connect(DSN) as conn:
            row = conn.execute('SELECT token_hash, expires_at-created_at, absolute_expires_at-created_at FROM admin_sessions WHERE account_id=%s ORDER BY created_at DESC LIMIT 1', (account_id,)).fetchone()
            self.assertGreaterEqual(row[1].total_seconds(), 59 * 60)
            self.assertLessEqual(row[1].total_seconds(), 61 * 60)
            self.assertGreaterEqual(row[2].total_seconds(), 479 * 60)
            self.assertLessEqual(row[2].total_seconds(), 481 * 60)
            conn.execute("UPDATE admin_sessions SET expires_at=now()+interval '1 minute' WHERE token_hash=%s", (row[0],))
            conn.commit()
        self.assertEqual(request(self.app, 'GET', '/admin/overview', token=new_token)['status'], 200)
        with db.connect(DSN) as conn:
            conn.execute("UPDATE admin_sessions SET absolute_expires_at=now()-interval '1 second' WHERE token_hash=%s", (token_hash(new_token),))
            conn.commit()
        self.assertEqual(request(self.app, 'GET', '/admin/overview', token=new_token)['status'], 403)

    def test_roles_permissions_and_role_grant_only_owner(self):
        owner_id, owner, _, owner_password = self.account('owner')
        admin_id, admin, _, admin_password = self.account('admin')
        support_id, support, _, support_password = self.account('support')
        viewer_id, viewer, _, viewer_password = self.account('viewer')
        owner_token = self.admin_login(owner, owner_password)
        admin_token = self.admin_login(admin, admin_password, '10.78.0.2')
        support_token = self.admin_login(support, support_password, '10.78.0.3')
        viewer_token = self.admin_login(viewer, viewer_password, '10.78.0.4')
        self.assertEqual(request(self.app, 'GET', '/admin/overview', token=viewer_token)['status'], 200)
        self.assertEqual(request(self.app, 'GET', '/admin/players', token=support_token)['status'], 200)
        self.assertEqual(request(self.app, 'POST', '/admin/settings', {'key': 'registration_enabled', 'value': False}, token=support_token)['status'], 403)
        self.assertEqual(request(self.app, 'POST', '/admin/settings', {'key': 'registration_enabled', 'value': False}, token=viewer_token)['status'], 403)
        self.assertEqual(request(self.app, 'POST', '/admin/roles', {'player_id': viewer_id, 'role': 'support', 'confirm': True}, token=admin_token)['status'], 403)
        granted = request(self.app, 'POST', '/admin/roles', {'player_id': viewer_id, 'role': 'support', 'confirm': True}, token=owner_token)
        self.assertEqual(granted['status'], 200, granted)
        with db.connect(DSN) as conn:
            self.assertEqual(conn.execute('SELECT role FROM accounts WHERE id=%s', (viewer_id,)).fetchone()[0], 'support')

    def test_block_unblock_revoke_compensation_and_reconcile(self):
        owner_id, owner, _, owner_password = self.account('owner')
        player_id, player, _, player_password = self.account('player', 'PlayerPasswordLong!123')
        owner_token = self.admin_login(owner, owner_password)
        player_login = request(self.app, 'POST', '/auth/login', {'username': player, 'password': player_password}, ip='10.80.0.1')
        self.assertEqual(player_login['status'], 200)
        blocked = request(self.app, 'POST', f'/admin/players/{player_id}/block', {'reason': 'проверка обращения', 'until': None}, token=owner_token)
        self.assertEqual(blocked['status'], 200, blocked)
        self.assertEqual(request(self.app, 'GET', '/auth/me', token=player_login['body']['access_token'])['status'], 401)
        self.assertEqual(request(self.app, 'POST', f'/admin/players/{player_id}/unblock', token=owner_token)['status'], 200)
        player_login = request(self.app, 'POST', '/auth/login', {'username': player, 'password': player_password}, ip='10.80.0.2')
        self.assertEqual(player_login['status'], 200)
        self.assertEqual(request(self.app, 'POST', '/admin/sessions/revoke', {'player_id': player_id}, token=owner_token)['status'], 200)
        self.assertEqual(request(self.app, 'GET', '/auth/me', token=player_login['body']['access_token'])['status'], 401)
        bad = request(self.app, 'POST', f'/admin/players/{player_id}/compensate', {'amount': 10, 'request_id': 'missing-reason', 'ticket': 'SUP-1'}, token=owner_token)
        self.assertEqual(bad['status'], 400)
        negative = request(self.app, 'POST', f'/admin/players/{player_id}/compensate', {'amount': -2000000, 'request_id': 'negative-' + uuid4().hex, 'reason': 'проверка минуса', 'ticket': 'SUP-2'}, token=owner_token)
        self.assertEqual(negative['status'], 400)
        request_id = 'comp-' + uuid4().hex
        payload = {'amount': 250, 'request_id': request_id, 'reason': 'компенсация', 'ticket': 'SUP-42'}
        first = request(self.app, 'POST', f'/admin/players/{player_id}/compensate', payload, token=owner_token)
        repeat = request(self.app, 'POST', f'/admin/players/{player_id}/compensate', payload, token=owner_token)
        self.assertEqual(first['status'], 200, first)
        self.assertEqual(repeat['status'], 200, repeat)
        self.assertEqual(first['body']['transfer_id'], repeat['body']['transfer_id'])
        with db.connect(DSN) as conn:
            wallet = conn.execute("SELECT balance FROM ledger_accounts WHERE account_key=%s", ('player:' + player.lower(),)).fetchone()[0]
            self.assertEqual(wallet, 1000250)
            self.assertTrue(__import__('server.ledger.api', fromlist=['reconcile']).reconcile(conn)['ok'])

    def test_support_limit_settings_revisions_rollback_and_audit(self):
        owner_id, owner, _, owner_password = self.account('owner')
        support_id, support, _, support_password = self.account('support')
        player_id, player, _, player_password = self.account('player', 'PlayerPasswordLong!123')
        owner_token = self.admin_login(owner, owner_password)
        support_token = self.admin_login(support, support_password, '10.81.0.2')
        with db.connect(DSN) as conn:
            conn.execute("INSERT INTO runtime_config(key,value) VALUES('support_compensation_limit','100') ON CONFLICT(key) DO UPDATE SET value='100'")
            conn.commit()
        over = request(self.app, 'POST', f'/admin/players/{player_id}/compensate', {'amount': 101, 'request_id': 'over-' + uuid4().hex, 'reason': 'лимит', 'ticket': 'SUP-1'}, token=support_token)
        self.assertEqual(over['status'], 403)
        changed = request(self.app, 'POST', '/admin/settings', {'key': 'registration_enabled', 'value': False, 'apply_at': 'now'}, token=owner_token)
        self.assertEqual(changed['status'], 200, changed)
        revision = changed['body']['revision']
        self.assertEqual(request(self.app, 'POST', '/admin/revisions/rollback', {'revision': revision}, token=owner_token)['status'], 200)
        audit = request(self.app, 'GET', '/admin/audit', token=owner_token, query=f'player={player_id}&limit=100')
        self.assertEqual(audit['status'], 200, audit)
        with db.connect(DSN) as conn:
            rows = conn.execute('SELECT actor,actor_role,target_account_id,ip,old_value,new_value FROM audit WHERE actor=%s ORDER BY id DESC LIMIT 20', (owner,)).fetchall()
            self.assertTrue(rows)
            self.assertTrue(any(row[1] == 'owner' and row[3] is not None for row in rows))


if __name__ == '__main__':
    unittest.main()
