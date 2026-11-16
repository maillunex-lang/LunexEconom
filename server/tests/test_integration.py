import io
import json
import os
import unittest
from datetime import datetime, timezone, timedelta
from server import db
from server.game_server import create_app, build_registry
from server.ledger.api import transfer
from server.clock.core import align_epoch, indices, MONTH_SECONDS, DAY_SECONDS, next_epoch
from server.catalog import load


def request(app, method, path, payload=None, auth=None):
    raw = json.dumps(payload or {}).encode()
    result = {}
    def start(status, headers):
        result['status'] = int(status.split()[0])
    response = b''.join(app({'REQUEST_METHOD': method, 'PATH_INFO': path, 'CONTENT_LENGTH': str(len(raw)), 'wsgi.input': io.BytesIO(raw), 'HTTP_AUTHORIZATION': auth or ''}, start))
    return result['status'], json.loads(response)


class TestClockCatalog(unittest.TestCase):
    def test_calendar(self):
        at = datetime(2026,11,15,4,0,tzinfo=timezone.utc)
        self.assertEqual(align_epoch(at), at)
        self.assertEqual(align_epoch(at-timedelta(seconds=1)), at-timedelta(days=1))
        self.assertEqual(next_epoch(at), at+timedelta(days=1))
        self.assertEqual(indices(at, at+timedelta(seconds=MONTH_SECONDS)), (30,1))
        self.assertEqual(DAY_SECONDS, 48*60)

    def test_catalog(self):
        from server.catalog import Catalog
        catalog = Catalog()
        for name in ('products', 'recipes', 'buildings'):
            entries = load(name)
            self.assertTrue(entries, f'{name} must not be empty')
            self.assertEqual(entries, catalog.data[name])
            ids = [entry['id'] for entry in entries]
            self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(catalog.version), 64)


@unittest.skipUnless(os.getenv('LUNEX_TEST_DATABASE_URL'), 'Set an ISOLATED PostgreSQL test DSN')
class TestPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ['LUNEX_TEST_DATABASE_URL']
        cls.app = create_app(cls.dsn)

    @classmethod
    def tearDownClass(cls):
        cls.app.close()

    def test_health_accounts_sessions(self):
        from uuid import uuid4
        user = 'test_' + uuid4().hex[:12]
        status, health = request(type(self).app,'GET','/health')
        self.assertEqual(status, 200)
        self.assertTrue(health['ok'])
        self.assertEqual(health['database'],'ok')
        self.assertIn('sha', health)
        self.assertEqual(request(type(self).app,'POST','/auth/register',{'consent_personal_data':True,'username':user,'email':user+'@example.com','password':'StrongPassword123!'})[0],201)
        self.assertEqual(request(type(self).app,'POST','/auth/register',{'consent_personal_data':True,'username':user,'email':user+'@example.com','password':'StrongPassword123!'})[0],409)
        self.assertEqual(request(type(self).app,'POST','/auth/login',{'username':user,'password':'wrong'})[0],401)
        status, login = request(type(self).app,'POST','/auth/login',{'consent_personal_data':True,'username':user,'email':user+'@example.com','password':'StrongPassword123!'})
        self.assertEqual(status,200)
        self.assertEqual(login['role'],'player')
        status, me = request(type(self).app,'GET','/auth/me',auth='Bearer '+login['token'])
        self.assertEqual(status,200)
        self.assertEqual(me['username'],user)
        self.assertEqual(me['role'],'player')
        self.assertEqual(request(type(self).app,'GET','/config')[0],503)
        self.assertEqual(request(type(self).app,'GET','/catalog')[0],200)

    def test_ledger_idempotent(self):
        from uuid import uuid4
        tag = uuid4().hex
        from server.ledger.api import account
        with db.connect(self.dsn) as conn:
            a = account(conn, 'player:' + tag, 'player')
            b = account(conn, 'city:' + tag, 'city')
            treasury = account(conn, 'system:treasury')
            transfer(conn,'seed:'+tag,treasury,a,500)
            first = transfer(conn,tag,a,b,120)
            self.assertEqual(transfer(conn,tag,a,b,120),first)
            with self.assertRaises(ValueError):
                transfer(conn,tag,a,b,121)
            balances = dict(conn.execute('SELECT id,balance FROM ledger_accounts WHERE id IN (%s,%s)', (a,b)).fetchall())
            self.assertEqual((balances[a],balances[b]),(380,120))
            entries = conn.execute('SELECT amount FROM ledger_entries WHERE transfer_id=%s', (first,)).fetchall()
            self.assertEqual(sum(value for value, in entries),0)
            self.assertEqual(len(entries),2)
            conn.commit()

    def test_migration_checksum(self):
        from server import platform
        with db.connect(self.dsn) as conn:
            db.migrate(conn, [platform])
            conn.commit()
            names = [r[0] for r in conn.execute('SELECT name FROM schema_migrations')]
            self.assertTrue(any('platform' in n for n in names))

if __name__ == '__main__': unittest.main()
