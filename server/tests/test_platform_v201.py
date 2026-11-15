"""V2-01 acceptance: PostgreSQL-backed platform invariants."""
import io
import json
import os
import random
import subprocess
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import rsa
from server import db
from server.clock import core
from server.game_server import create_app
from server.ledger.api import account,transfer,post,reconcile
from server.platform import settings
from server.registry import Registry
from tools.sign_config import sign,verify,canonical

DSN=os.getenv('LUNEX_TEST_DATABASE_URL')


def request(app,method,path,payload=None,token='',ip='127.0.0.1',admin_token='',host='localhost:18777',query=''):
    body=json.dumps(payload or {}).encode()
    result={}
    def start(status,headers):
        result['status']=int(status.split()[0])
    environ={'REQUEST_METHOD':method,'PATH_INFO':path,'CONTENT_LENGTH':str(len(body)), 'wsgi.input':io.BytesIO(body),'REMOTE_ADDR':ip,'HTTP_HOST':host,'HTTP_AUTHORIZATION':'Bearer '+token if token else '','HTTP_X_ADMIN_TOKEN':admin_token,'QUERY_STRING':query}
    raw=b''.join(app(environ,start)).decode()
    return result['status'],json.loads(raw)


@unittest.skipUnless(DSN,'Set LUNEX_TEST_DATABASE_URL to an isolated PostgreSQL database')
class TestAuthAndAdmin(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=create_app(DSN)
    @classmethod
    def tearDownClass(cls): cls.app.close()

    def _user(self):
        name='u'+uuid4().hex[:12]
        data={'username':name,'email':name.upper()+'@EXAMPLE.COM','password':'veryStrongPassword!23'}
        ip='10.9.'+str(int(uuid4().hex[:2],16)%250+1)+'.'+str(int(uuid4().hex[:2],16)%250+1)
        status,profile=request(type(self).app,'POST','/auth/register',data,ip=ip)
        self.assertEqual(status,201,profile)
        return data,profile

    def test_auth_and_capital(self):
        data,profile=self._user()
        with db.connect(DSN) as conn:
            row=conn.execute('SELECT email,role,is_blocked FROM accounts WHERE id=%s',(profile['id'],)).fetchone()
            self.assertEqual(row,(data['email'].lower(),'player',False))
        status,login=request(type(self).app,'POST','/auth/login',{'username':data['username'],'password':data['password']},ip='10.9.0.2')
        self.assertEqual(status,200,login)
        self.assertEqual(login['expires_in'],1800)
        status,me=request(type(self).app,'GET','/auth/me',token=login['access_token'])
        self.assertEqual((status,me['role']),(200,'player'))
        with db.connect(DSN) as conn:
            previous_seen=conn.execute('SELECT seen_at FROM presence WHERE account_id=%s',(profile['id'],)).fetchone()[0]
        request(type(self).app,'GET','/auth/me',token=login['access_token'])
        with db.connect(DSN) as conn:
            current_seen=conn.execute('SELECT seen_at FROM presence WHERE account_id=%s',(profile['id'],)).fetchone()[0]
        self.assertEqual(previous_seen,current_seen)  # <=30s presence throttle
        status,wallet=request(type(self).app,'GET','/ledger/balance',token=login['access_token'])
        self.assertEqual((status,wallet['balance']),(200,1000000))
        status,history=request(type(self).app,'GET','/ledger/history',token=login['access_token'],query='page=1&limit=1')
        self.assertEqual(status,200)
        self.assertEqual(len(history['items']),1)
        self.assertEqual(request(type(self).app,'GET','/ledger/history',token=login['access_token'],query='page=-1')[0],400)
        status,refreshed=request(type(self).app,'POST','/auth/refresh',{'refresh_token':login['refresh_token']})
        self.assertEqual(status,200,refreshed)
        self.assertNotEqual(refreshed['refresh_token'],login['refresh_token'])
        self.assertEqual(request(type(self).app,'POST','/auth/refresh',{'refresh_token':login['refresh_token']})[0],401)
        self.assertEqual(request(type(self).app,'POST','/auth/logout',{'refresh_token':refreshed['refresh_token']})[0],200)
        self.assertEqual(request(type(self).app,'GET','/auth/me',token=refreshed['access_token'])[0],401)
        status,again=request(type(self).app,'POST','/auth/login',{'username':data['username'],'password':data['password']},ip='10.9.0.3')
        self.assertEqual(status,200)
        from server.platform.security import token_hash
        with db.connect(DSN) as conn:
            conn.execute("UPDATE sessions SET expires_at=now()-interval '1 second' WHERE token_hash=%s",(token_hash(again['access_token']),))
            conn.commit()
        self.assertEqual(request(type(self).app,'GET','/auth/me',token=again['access_token'])[0],401)
        self.assertEqual(request(type(self).app,'POST','/auth/refresh',{'refresh_token':again['refresh_token']})[0],200)
        with db.connect(DSN) as conn:
            self.assertTrue(reconcile(conn)['ok'])

    def test_operator_ui_restricted_to_localhost(self):
        def probe(ip,host,forwarded=None):
            result={}
            env={'REQUEST_METHOD':'GET','PATH_INFO':'/operator-ui','REMOTE_ADDR':ip,'HTTP_HOST':host,'CONTENT_LENGTH':'0','wsgi.input':io.BytesIO(b'')}
            if forwarded: env['HTTP_X_FORWARDED_FOR']=forwarded
            body=b''.join(type(self).app(env,lambda status,headers: result.update(code=int(status.split()[0]))))
            return result['code'],body
        self.assertEqual(probe('203.0.113.10','localhost:18777')[0],403)
        self.assertEqual(probe('127.0.0.1','rikagro.ru')[0],403)
        self.assertEqual(probe('127.0.0.1','localhost:18777','203.0.113.10')[0],403)
        status,html=probe('127.0.0.1','localhost:18777')
        self.assertEqual(status,200)
        self.assertIn(b'LunexEconom V2',html)

    def test_registration_validation_and_rate_limits(self):
        name='n'+uuid4().hex[:10]
        self.assertEqual(request(type(self).app,'POST','/auth/register',{'username':name,'email':'bad','password':'goodPassword111'})[0],400)
        self.assertEqual(request(type(self).app,'POST','/auth/register',{'username':name,'email':'good@example.com','password':'short'})[0],400)
        self.assertEqual(request(type(self).app,'POST','/auth/register',{'username':'bad:name','email':'good@example.com','password':'goodPassword111'})[0],400)
        ip='10.23.'+str(int(uuid4().hex[:2],16)%250+1)+'.'+str(int(uuid4().hex[:2],16)%250+1)
        for i in range(8):
            status,_=request(type(self).app,'POST','/auth/login',{'username':'none_'+name,'password':'not-known'},ip=ip)
            self.assertEqual(status,401)
        self.assertEqual(request(type(self).app,'POST','/auth/login',{'username':'none_'+name,'password':'not-known'},ip=ip)[0],429)
        self.assertEqual(request(type(self).app,'POST','/auth/login',{'username':'another','password':'not-known'},ip=ip)[0],401)
        for i in range(111):
            username='missing'+str(i)+'_'+name
            self.assertEqual(request(type(self).app,'POST','/auth/login',{'username':username,'password':'not-known'},ip=ip)[0],401)
        self.assertEqual(request(type(self).app,'POST','/auth/login',{'username':'last_attempt','password':'not-known'},ip=ip)[0],429)
        ip='10.24.'+str(int(uuid4().hex[:2],16)%250+1)+'.'+str(int(uuid4().hex[:2],16)%250+1)
        for i in range(10):
            u='r'+uuid4().hex[:10]
            status,_=request(type(self).app,'POST','/auth/register',{'username':u,'email':u+'@example.com','password':'goodPassword111'},ip=ip)
            self.assertEqual(status,201)
        u='r'+uuid4().hex[:10]
        self.assertEqual(request(type(self).app,'POST','/auth/register',{'username':u,'email':u+'@example.com','password':'goodPassword111'},ip=ip)[0],429)

    def test_admin_loopback_role_and_block(self):
        data,_=self._user()
        secret='TEST_ONLY_ADMIN_ACCESS_TOKEN_123456789012345'
        with patch.dict(os.environ,{'LUNEX_ADMIN_TOKEN':secret}):
            self.assertEqual(request(type(self).app,'GET','/admin/overview',ip='10.1.2.3',admin_token=secret)[0],403)
            self.assertEqual(request(type(self).app,'GET','/admin/overview',admin_token='incorrect')[0],403)
            self.assertEqual(request(type(self).app,'GET','/admin/overview',admin_token=secret,host='rikagro.ru')[0],403)
            status,overview=request(type(self).app,'GET','/admin/overview',admin_token=secret)
            self.assertEqual(status,200,overview)
            self.assertIn('online',overview)
            self.assertIn('pool',overview)
            status,response=request(type(self).app,'POST','/admin/settings',{'key':'registration_enabled','value':True,'apply_at':'now'},admin_token=secret)
            self.assertEqual(status,200,response)
            self.assertEqual(request(type(self).app,'GET','/admin/revisions',admin_token=secret)[0],200)
            self.assertEqual(request(type(self).app,'GET','/admin/audit',admin_token=secret)[0],200)
            self.assertEqual(request(type(self).app,'POST','/admin/accounts/block',{'username':data['username'],'blocked':True},admin_token=secret)[0],200)
            self.assertEqual(request(type(self).app,'POST','/auth/login',{'username':data['username'],'password':data['password']},ip='10.9.0.21')[0],401)
        env=dict(os.environ,LUNEX_DATABASE_URL=DSN)
        command=[sys.executable,'-m','server.platform.accounts_admin','grant',data['username'],'developer']
        p=subprocess.run(command,env=env,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        with db.connect(DSN) as conn:
            row=conn.execute('SELECT role FROM accounts WHERE username=%s',(data['username'],)).fetchone()
            self.assertEqual(row[0],'developer')
        p=subprocess.run([sys.executable,'-m','server.platform.accounts_admin','revoke',data['username']],env=env,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)


@unittest.skipUnless(DSN,'Requires PostgreSQL')
class TestLedger(unittest.TestCase):
    def test_ten_thousand_and_reconcile(self):
        tag=uuid4().hex[:10]
        rng=random.Random(20261115)
        with db.connect(DSN) as conn:
            ids=[account(conn,'player:stress'+tag+str(i),'player') for i in range(3)]
            treasury=account(conn,'system:treasury')
            for i,aid in enumerate(ids):
                transfer(conn,'stress-fund'+tag+str(i),treasury,aid,50000)
            for i in range(10000):
                a,b=rng.sample(ids,2)
                transfer(conn,'stress-'+tag+'-'+str(i),a,b,rng.randint(1,5))
            tx=post(conn,'stress-multi-'+tag,[(ids[0],-12),(ids[1],7),(ids[2],5)])
            self.assertEqual(post(conn,'stress-multi-'+tag,[(ids[2],5),(ids[0],-12),(ids[1],7)]),tx)
            with self.assertRaises(ValueError):
                post(conn,'stress-multi-'+tag,[(ids[0],-9),(ids[1],9)])
            stats=reconcile(conn)
            self.assertTrue(stats['ok'],stats)
            self.assertEqual(stats['total_balance'],0)
            conn.commit()

    def test_parallel_transfer_and_idempotency(self):
        tag=uuid4().hex
        with db.connect(DSN) as conn:
            payer=account(conn,'player:parallel'+tag,'player')
            treasury=account(conn,'system:treasury')
            recipient=account(conn,'system:market')
            transfer(conn,'parallel-seed'+tag,treasury,payer,100)
            conn.commit()
        def attempt(i):
            with db.connect(DSN) as conn:
                try:
                    tx=transfer(conn,'parallel-'+tag+'-'+str(i),payer,recipient,3)
                    conn.commit()
                    return tx
                except ValueError:
                    conn.rollback()
                    return None
        with ThreadPoolExecutor(max_workers=12) as ex:
            receipts=list(ex.map(attempt,range(60)))
        successful=[x for x in receipts if x is not None]
        self.assertEqual(len(successful),33)
        with db.connect(DSN) as conn:
            self.assertEqual(conn.execute('SELECT balance FROM ledger_accounts WHERE id=%s',(payer,)).fetchone()[0],1)
        def once(_):
            with db.connect(DSN) as conn:
                tx=transfer(conn,'same-id-'+tag,recipient,payer,1)
                conn.commit()
                return tx
        with ThreadPoolExecutor(max_workers=8) as ex:
            ids=list(ex.map(once,range(8)))
        self.assertEqual(len(set(ids)),1)
        with db.connect(DSN) as conn:
            self.assertTrue(reconcile(conn)['ok'])


@unittest.skipUnless(DSN,'Requires PostgreSQL')
class TestClockSettingsAndSigning(unittest.TestCase):
    def test_atomic_ticks_order_catchup_retry(self):
        tag='clock-'+uuid4().hex[:10]
        r=Registry()
        def write(name):
            def fn(conn,idx):
                conn.execute('INSERT INTO audit(actor,action) VALUES(%s,%s)',(tag,name+':'+str(idx)))
            return fn
        r.tick('daily','after',write('after'),order=20)
        r.tick('daily','before',write('before'),order=10)
        r.tick('monthly','close',write('month'),order=10)
        epoch=datetime(2026,11,15,4,0,tzinfo=timezone.utc)
        with db.connect(DSN) as conn:
            conn.execute('DELETE FROM game_ticks')
            conn.execute('DELETE FROM tick_receipts')
            conn.commit()
            out=core.run_pending(conn,r,epoch,epoch+timedelta(seconds=2*core.DAY_SECONDS),limit=5)
            self.assertEqual(out['processed'],3,out)
            conn.commit()
            rows=conn.execute('SELECT action FROM audit WHERE actor=%s ORDER BY id',(tag,)).fetchall()
            self.assertEqual([x[0] for x in rows],['before:0','after:0','month:0','before:1','after:1','before:2','after:2'])
            conn.commit()
        with db.connect(DSN) as conn:
            self.assertEqual(core.run_pending(conn,r,epoch,epoch+timedelta(seconds=2*core.DAY_SECONDS))['processed'],0)
        r.tick('daily','failure',lambda conn,idx: (_ for _ in ()).throw(RuntimeError('test-failure')) if idx==3 else None,order=30)
        with db.connect(DSN) as conn:
            failed=core.run_pending(conn,r,epoch,epoch+timedelta(seconds=4*core.DAY_SECONDS))
            self.assertEqual(failed['processed'],0)
            self.assertIn('test-failure',failed['error'])
        with db.connect(DSN) as conn:
            self.assertEqual(conn.execute('SELECT completed FROM game_ticks WHERE day_index=3').fetchone()[0],False)
            count=conn.execute("SELECT count(*) FROM audit WHERE actor=%s AND action='before:3'",(tag,)).fetchone()[0]
            self.assertEqual(count,0)
        r.tick_handlers['daily']=[entry for entry in r.tick_handlers['daily'] if entry[1]!='failure']
        with db.connect(DSN) as conn:
            self.assertEqual(core.run_pending(conn,r,epoch,epoch+timedelta(seconds=4*core.DAY_SECONDS))['processed'],2)
            conn.commit()
            self.assertEqual(conn.execute('SELECT count(*) FROM game_ticks WHERE completed').fetchone()[0],5)

    def test_settings_types_scheduling_rollback(self):
        defaults={'test_count':5}
        bounds={'test_count':[0,10]}
        with db.connect(DSN) as conn,patch.dict(os.environ,{'LUNEX_FLAG_TEST_COUNT':'6'}):
            initial=conn.execute('SELECT epoch FROM platform_clock WHERE id=1').fetchone()[0]
            self.assertEqual(settings.read_settings(conn,defaults,bounds)['test_count'],6)
            now=settings.change(conn,'test_count',7,'now','test',defaults,bounds)
            self.assertEqual(settings.read_settings(conn,defaults,bounds)['test_count'],7)
            future=settings.change(conn,'test_count',9,'next_month','test',defaults,bounds)
            self.assertEqual(settings.read_settings(conn,defaults,bounds)['test_count'],7)
            with self.assertRaises(ValueError): settings.change(conn,'test_count',11,'now','test',defaults,bounds)
            with self.assertRaises(ValueError): settings.change(conn,'test_count',True,'now','test',defaults,bounds)
            try:
                conn.execute('UPDATE platform_clock SET epoch=now()-interval \'2 days\' WHERE id=1')
                self.assertEqual(settings.read_settings(conn,defaults,bounds)['test_count'],9)
                settings.rollback(conn,future['revision'],'test',defaults,bounds)
                self.assertEqual(settings.read_settings(conn,defaults,bounds)['test_count'],7)
            finally:
                conn.execute('UPDATE platform_clock SET epoch=%s WHERE id=1',(initial,))
                conn.commit()

    def test_signature_and_config_endpoint(self):
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        payload={'version':'v2.1','api':'/lunexeconom/api','features':{'enabled':True}}
        encoded,signature=sign(key,payload)
        self.assertTrue(verify(key.public_key(),encoded,signature))
        self.assertFalse(verify(key.public_key(),encoded,signature[:-4]+'AAAA'))
        with db.connect(DSN) as conn:
            rev=conn.execute('SELECT COALESCE(MAX(revision),0)+1 FROM signed_client_config').fetchone()[0]
            conn.execute('INSERT INTO signed_client_config(revision,payload_b64,signature) VALUES(%s,%s,%s)',(rev,encoded,signature))
            conn.commit()
        app=create_app(DSN)
        try:
            status,config=request(app,'GET','/config')
            self.assertEqual(status,200)
            self.assertTrue(verify(key.public_key(),config['payload_b64'],config['signature']))
        finally: app.close()

    def test_background_worker(self):
        with db.connect(DSN) as conn:
            conn.execute('DELETE FROM game_ticks')
            conn.execute('DELETE FROM tick_receipts')
            conn.execute('UPDATE platform_clock SET epoch=now()-interval \'3 hours\' WHERE id=1')
            conn.commit()
        with patch.dict(os.environ,{'LUNEX_TICK_INTERVAL':'0.1'}):
            app=create_app(DSN,start_tick=True)
            try:
                total=0
                for _ in range(35):
                    time.sleep(0.1)
                    with db.connect(DSN) as conn:
                        total=conn.execute('SELECT count(*) FROM game_ticks WHERE completed').fetchone()[0]
                        if total>=4: break
                self.assertGreaterEqual(total,4)
            finally: app.close()
