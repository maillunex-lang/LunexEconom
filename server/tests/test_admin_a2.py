"""A2 real PostgreSQL acceptance tests, without production credentials."""
import json
import os
import unittest
from pathlib import Path
from uuid import uuid4

from server import db
from server.game_server import create_app
from server.platform import admin_economy
from server.tests.test_admin_a1 import request

DSN = os.getenv('LUNEX_TEST_DATABASE_URL')
ROUTES = ['/admin/economy', '/admin/economy/history', '/admin/cities',
          '/admin/world/events', '/admin/parcels', '/admin/server',
          '/admin/ticks', '/admin/errors', '/admin/alerts']


class AdminA2Static(unittest.TestCase):
    def test_dashboard_offline_and_sections(self):
        root = Path(__file__).resolve().parents[2] / 'web' / 'admin'
        html = (root/'index.html').read_text()
        js = (root/'app.js').read_text()
        css = (root/'styles.css').read_text()
        for name in ('economy', 'cities', 'events', 'server', 'alerts'):
            self.assertIn('data-tab="'+name+'"',html)
        for name in ('Экономика','Города','События','Сервер и тики','Алерты'):
            self.assertIn(name, html)
        for text in ('sessionStorage','/economy/history','<svg','request_id'):
            self.assertIn(text,js)
        self.assertNotIn('http://',html+js+css)
        self.assertNotIn('https://',html+js+css)
        self.assertIn('prefers-color-scheme: light',css)
        self.assertIn('max-width: 400px',css)


@unittest.skipUnless(DSN, 'Set LUNEX_TEST_DATABASE_URL to isolated PostgreSQL 16')
class AdminA2Database(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = staticmethod(create_app(DSN))

    @classmethod
    def tearDownClass(cls):
        cls.app.close()

    def admin(self, role):
        unique = uuid4().hex[:13]
        username = 'a'+unique
        passwd = 'Test_Valid_Admin_Pass_123!'
        registration = request(self.app,'POST','/auth/register',
                               {'consent_personal_data':True,'username':username, 'email':username+'@example.test','password':passwd},
                               ip='10.30.'+str(int(unique[:2],16)%230+1)+'.10')
        self.assertEqual(registration['status'],201,registration)
        with db.connect(DSN) as conn:
            conn.execute('UPDATE accounts SET role=%s WHERE id=%s',
                         (role,registration['body']['id']))
            conn.commit()
        auth=request(self.app,'POST','/admin/login',{'username':username,'password':passwd},
                     ip='10.31.'+str(int(unique[2:4],16)%230+1)+'.11')
        self.assertEqual(auth['status'],200,auth)
        return auth['body']['token'],registration['body']['id']

    def call(self, path, token, query='', method='GET', payload=None):
        return request(self.app,method,path,payload,token=token,query=query)

    def test_production_carry_exact_and_receipt_idempotent(self):
        for volume in (1,3,17,300,10000):
            for load in (0,1,17,5000,9999,10000):
                for old in (0,1,37,9999):
                    made, new_carry = divmod(volume*load+old,10000)
                    self.assertEqual(admin_economy._reconstitute_output(volume,load,new_carry),made)
        with db.connect(DSN) as conn:
            day=conn.execute('SELECT COALESCE(MAX(day_index),-1)+1 FROM admin_production_receipts').fetchone()[0]
            admin_economy.capture_production(conn,day)
            admin_economy.capture_production(conn,day)
            self.assertEqual(conn.execute('SELECT count(*) FROM admin_production_receipts WHERE day_index=%s',(day,)).fetchone()[0],1)
            conn.commit()

    def test_all_routes_require_session(self):
        for path in ROUTES:
            self.assertEqual(self.call(path,'')['status'],403,path)
        self.assertEqual(self.call('/admin/cities/1/growth','',method='POST',payload={})['status'],403)

    def test_viewer_all_reads_and_cannot_change_growth(self):
        token,_=self.admin('viewer')
        for path in ROUTES:
            result=self.call(path,token)
            self.assertEqual(result['status'],200,(path,result))
        self.assertEqual(self.call('/admin/cities/ufa/growth',token,method='POST',
                         payload={'enabled':False,'reason':'test viewer','request_id':'viewer-request-1'})['status'],403)

    def test_economy_reconcile_and_non_disclosure(self):
        token,player=self.admin('owner')
        for path in ['/admin/economy','/admin/server','/admin/alerts','/admin/players/'+str(player)]:
            result=self.call(path,token)
            self.assertEqual(result['status'],200,(path,result))
            response=json.dumps(result['body']).lower()
            for forbidden in ('password','token_hash','email'):
                self.assertNotIn(forbidden,response,path)
        data=self.call('/admin/economy',token)['body']
        self.assertTrue(data['reconcile']['ok'],data)
        self.assertEqual(data['ledger_total'],0)
        self.assertEqual(data['reconcile']['total_balance'],0)
        self.assertEqual(len(self.call('/admin/cities',token)['body']['items']),20)
        self.assertIn('migrations',self.call('/admin/server',token)['body'])

    def test_daily_history_idempotent_and_cursor(self):
        token,_=self.admin('admin')
        with db.connect(DSN) as conn:
            day=conn.execute('SELECT COALESCE(MAX(day_index),-1)+1 FROM game_ticks').fetchone()[0]
            conn.execute('INSERT INTO game_ticks(day_index,completed,duration_ms) VALUES(%s,true,30)',(day,))
            admin_economy.snapshot(conn,day)
            before=conn.execute('SELECT players FROM admin_daily_stats WHERE day_index=%s',(day,)).fetchone()[0]
            conn.execute("INSERT INTO accounts(username,password_hash) VALUES(%s,'unusable')",('a2demo'+uuid4().hex[:15],))
            admin_economy.snapshot(conn,day)
            after=conn.execute('SELECT players FROM admin_daily_stats WHERE day_index=%s',(day,)).fetchone()[0]
            self.assertEqual(before,after)
            conn.commit()
        result=self.call('/admin/economy/history',token,query='days=90&limit=1')
        self.assertEqual(result['status'],200,result)
        self.assertLessEqual(len(result['body']['items']),1)
        self.assertEqual(self.call('/admin/economy/history',token,query='days=91')['status'],400)
        self.assertEqual(self.call('/admin/economy/history',token,query='limit=101')['status'],400)

    def test_growth_idempotent_audit_and_validation(self):
        token,_=self.admin('admin')
        request_id='a2-growth-'+uuid4().hex
        payload={'enabled':False,'reason':'Приёмочный тест','request_id':request_id}
        result=self.call('/admin/cities/ufa/growth',token,method='POST',payload=payload)
        self.assertEqual(result['status'],200,result)
        try:
            replay=self.call('/admin/cities/ufa/growth',token,method='POST',payload=payload)
            self.assertEqual(replay['status'],200,replay)
            self.assertTrue(replay['body']['replayed'])
            changed={**payload,'enabled':True}
            self.assertEqual(self.call('/admin/cities/ufa/growth',token,method='POST',payload=changed)['status'],409)
            with db.connect(DSN) as conn:
                count=conn.execute("SELECT count(*) FROM audit WHERE action='world.growth_enabled' AND payload->>'request_id'=%s",(request_id,)).fetchone()[0]
                self.assertEqual(count,1)
                conn.commit()
        finally:
            self.call('/admin/cities/ufa/growth',token,method='POST',
                      payload={'enabled':True,'reason':'Возврат после теста','request_id':'a2-reset-'+uuid4().hex})

    def test_limits_events_and_alerts(self):
        token,_=self.admin('owner')
        for path in ('/admin/ticks','/admin/errors','/admin/world/events','/admin/parcels','/admin/cities'):
            self.assertEqual(self.call(path,token,query='limit=101')['status'],400,path)
        self.assertEqual(self.call('/admin/world/events',token,query='after=banana')['status'],400)
        self.assertEqual(self.call('/admin/parcels',token,query='city=no-such-city')['status'],400)
        for path in ('/admin/server','/admin/alerts'):
            self.assertEqual(self.call(path,token)['status'],200,path)

    def test_player_wallet_entries_and_audit(self):
        token,pid=self.admin('admin')
        result=self.call('/admin/players/'+str(pid),token)
        self.assertEqual(result['status'],200,result)
        self.assertIn('wallet_entries',result['body'])
        self.assertIn('audit_actions',result['body'])
        self.assertIn('stage',str(result['body']) if result['body']['enterprises'] else 'stage')

    def test_city_and_parcel_cursors(self):
        token, pid=self.admin('owner')
        first=self.call('/admin/cities',token,query='limit=3')
        self.assertEqual(first['status'],200,first)
        self.assertEqual(len(first['body']['items']),3)
        after=first['body']['next_after']
        following=self.call('/admin/cities',token,query='limit=3&after='+after)
        self.assertEqual(following['status'],200,following)
        self.assertFalse(set(x['id'] for x in first['body']['items']) &
                         set(x['id'] for x in following['body']['items']))
        a=int(uuid4().hex[:8],16)+100000000
        with db.connect(DSN) as conn:
            conn.execute("INSERT INTO world_parcels(px,py,city_id,owner_kind,owner_ref) VALUES(%s,%s,'ufa','player',%s)",(a,0,str(pid)))
            conn.execute("INSERT INTO world_parcels(px,py,city_id,owner_kind,owner_ref) VALUES(%s,%s,'ufa','player',%s)",(a+1,0,str(pid)))
            conn.commit()
        try:
            page1=self.call('/admin/parcels',token,query=f'owner={pid}&city=ufa&limit=1')
            self.assertEqual(page1['status'],200,page1)
            self.assertEqual(len(page1['body']['items']),1)
            cursor=page1['body']['next_after']
            page2=self.call('/admin/parcels',token,query=f'owner={pid}&city=ufa&limit=1&after={cursor}')
            self.assertEqual(page2['status'],200,page2)
            self.assertNotEqual(page1['body']['items'][0]['px'],page2['body']['items'][0]['px'])
            self.assertEqual(self.call('/admin/parcels',token,query='after=bad-cursor')['status'],400)
        finally:
            with db.connect(DSN) as conn:
                conn.execute('DELETE FROM world_parcels WHERE px IN (%s,%s) AND owner_ref=%s',(a,a+1,str(pid)))
                conn.commit()

    def test_failed_tick_log_and_alert_redaction(self):
        token,_=self.admin('owner')
        with db.connect(DSN) as conn:
            day=conn.execute('SELECT COALESCE(MAX(day_index),0)+10000 FROM game_ticks').fetchone()[0]
            conn.execute('INSERT INTO game_ticks(day_index,duration_ms,error,completed) VALUES(%s,35000,%s,false)',
                         (day,'password=SECRET token_hash=SECRET email=private'))
            conn.commit()
        try:
            for path in ('/admin/ticks','/admin/errors','/admin/alerts','/admin/server'):
                result=self.call(path,token)
                self.assertEqual(result['status'],200,(path,result))
                body=json.dumps(result['body']).lower()
                for forbidden in ('password','token_hash','email'):
                    self.assertNotIn(forbidden,body,path)
            alerts=self.call('/admin/alerts',token)['body']['items']
            codes={item['code'] for item in alerts}
            self.assertIn('tick_failed',codes)
            self.assertIn('tick_slow',codes)
            errors=self.call('/admin/errors',token)['body']['items']
            self.assertTrue(any(e['day_index']==day and e['error_code']=='tick_failed' for e in errors))
            # Reopening the page does not duplicate the diagnostic receipt.
            self.call('/admin/errors',token)
            with db.connect(DSN) as conn:
                count=conn.execute("SELECT count(*) FROM admin_error_log WHERE origin='tick' AND day_index=%s",(day,)).fetchone()[0]
                self.assertEqual(count,1)
        finally:
            with db.connect(DSN) as conn:
                conn.execute('DELETE FROM admin_error_log WHERE origin=%s AND day_index=%s',('tick',day))
                conn.execute('DELETE FROM game_ticks WHERE day_index=%s',(day,))
                conn.commit()
