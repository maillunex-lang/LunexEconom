"""SEC1 public route authorization, malformed input and HTTP envelope."""
import io
import json
import os
import unittest
from uuid import uuid4
from server import db
from server.game_server import create_app, MAX_BODY
from server.tests.test_platform_v201 import request
from server.platform.security import token_hash

DSN=os.getenv('LUNEX_TEST_DATABASE_URL')


def probe(app,method,path,body=b'{}',token='',query='',declared=None):
    result={}
    def started(status,headers):
        result['code']=int(status.split()[0]);result['headers']=dict(headers)
    env={'REQUEST_METHOD':method,'PATH_INFO':path,'QUERY_STRING':query,
      'CONTENT_LENGTH':str(len(body) if declared is None else declared),
      'wsgi.input':io.BytesIO(body),'REMOTE_ADDR':'10.160.1.1',
      'HTTP_HOST':'localhost:18777',
      'HTTP_AUTHORIZATION':'Bearer '+token if token else ''}
    raw=b''.join(app(env,started))
    result['body']=json.loads(raw) if raw else None
    return result


@unittest.skipUnless(DSN,'Requires isolated PostgreSQL 16')
class SecurityInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=staticmethod(create_app(DSN))
    @classmethod
    def tearDownClass(cls):cls.app.close()

    def player(self):
        name='n'+uuid4().hex[:12]
        password='ReallyStrongPassword123!'
        details={'consent_personal_data':True,'username':name,'email':name+'@example.test','password':password}
        self.assertEqual(request(self.app,'POST','/auth/register',details,ip='10.160.'+str(int(name[1:3],16)%240+1)+'.'+str(int(name[3:5],16)%240+1))[0],201)
        result=request(self.app,'POST','/auth/login',{'username':name,'password':password},ip='10.161.'+str(int(name[5:7],16)%240+1)+'.'+str(int(name[7:9],16)%240+1))
        self.assertEqual(result[0],200)
        return result[1]['access_token']

    def test_registry_auth_matrix(self):
        routes=self.app.registry.routes
        protected=[]
        public={'/health','/auth/register','/auth/login','/auth/refresh','/auth/logout','/config',
          '/world/cities','/world/chunk','/world/events','/world/routes','/land/parcels',
          '/catalog','/clock','/retail/ratings','/market/history','/auth/me','/me'}
        public.update(path for _,path in routes if path.startswith('/world/cities/') or path.startswith('/market/'))
        public.update({'/admin/login'})
        public.update(path for _,path in routes if path.startswith('/catalog/'))
        for (method,path) in routes:
            concrete=path.replace('{id}','999999999')
            if path.startswith('/admin/') and path!='/admin/login':
                self.assertEqual(probe(self.app,method,concrete)['code'],403,(method,path))
            elif path not in public:
                protected.append((method,path))
                code=probe(self.app,method,concrete,body=json.dumps({'px':1,'py':1,'request_id':'sec-input','cells':[]}).encode())['code']
                self.assertEqual(code,401,(method,path,code))
        self.assertGreaterEqual(len(protected),15)

    def test_foreign_enterprise_indistinguishable(self):
        outsider=self.player()
        paths=['/enterprises/{id}','/enterprises/{id}/settings','/enterprises/{id}/sell',
          '/enterprises/{id}/demolish','/enterprises/{id}/report',
          '/enterprises/{id}/supply','/enterprises/{id}/supply/policy',
          '/enterprises/{id}/cells','/enterprises/{id}/sales']
        methods=['GET','POST','PUT']
        with db.connect(DSN) as conn:
            existing=conn.execute('SELECT id FROM enterprises WHERE sold_at IS NULL ORDER BY id LIMIT 1').fetchone()
        self.assertIsNotNone(existing)
        for path in paths:
            for method in methods:
                if (method,path) not in self.app.registry.routes:continue
                a=probe(self.app,method,path.replace('{id}',str(existing[0])),body=json.dumps({'request_id':'security-input-probe'}).encode(),token=outsider)
                b=probe(self.app,method,path.replace('{id}','9223372036854775807'),body=json.dumps({'request_id':'security-input-probe'}).encode(),token=outsider)
                self.assertEqual((a['code'],a['body']),(404,{'error':'not_found'}),(method,path,a))
                self.assertEqual((a['code'],a['body']),(b['code'],b['body']),(method,path,b))

    def test_expired_blocked_and_unknown_credentials(self):
        token=self.player()
        for path in ['/auth/me','/ledger/balance','/enterprises']:
            self.assertEqual(probe(self.app,'GET',path,token='bad-token')['code'],401)
        with db.connect(DSN) as conn:
            conn.execute("UPDATE sessions SET expires_at=now()-interval '2 hours' WHERE token_hash=%s",(token_hash(token),))
        self.assertEqual(probe(self.app,'GET','/auth/me',token=token)['code'],401)
        newer=self.player()
        with db.connect(DSN) as conn:
            conn.execute('UPDATE accounts SET is_blocked=true WHERE id=(SELECT account_id FROM sessions WHERE token_hash=%s)',(token_hash(newer),))
        self.assertEqual(probe(self.app,'GET','/auth/me',token=newer)['code'],401)

    def test_http_malformed_and_limits(self):
        malformed=[b'',b'{',b'null',b'[]',b'123',b'"string"',b'\xff',b'{}x']
        for value in malformed:
            result=probe(self.app,'POST','/auth/register',value)
            self.assertIn(result['code'],(400,413,422),result)
        too_big=probe(self.app,'POST','/auth/register',b'{}',declared=MAX_BODY+1)
        self.assertEqual(too_big['code'],413)
        missing=probe(self.app,'POST','/auth/register',b'{}',declared='')
        self.assertEqual(missing['code'],411)
        header=probe(self.app,'GET','/health')
        self.assertEqual(header['headers']['Content-Type'],'application/json; charset=utf-8')
        self.assertNotIn('Access-Control-Allow-Origin',header['headers'])
        self.assertNotIn('Server',header['headers'])
        self.assertNotIn('Traceback',str(header['body']))

    def test_fuzz_invalid_fields(self):
        samples=[None,False,True,1.5,-1,2**70,{},[],['x'],{'nested':1},'DROP TABLE accounts;','\u0000control','имя']
        token=self.player()
        for value in samples:
            body={'request_id':'security-fuzz','building_id':'field','px':value,'py':1,'x':1,'y':1}
            r=probe(self.app,'POST','/enterprises',json.dumps(body).encode(),token=token)
            self.assertIn(r['code'],(400,409,422),r)
            self.assertNotIn('Traceback',str(r['body']))
        for value in samples:
            result=probe(self.app,'POST','/auth/register',json.dumps({'consent_personal_data':True,'username':value,'email':'test@example.org','password':'PasswordSecure123'}).encode())
            self.assertIn(result['code'],(400,409,422,429),result)
