"""A9 authenticated integration, GitHub stubs and public link security."""
import hashlib
import io
import urllib.parse
import json
import tempfile
import time
import unittest
from pathlib import Path

from portal import auth, db
from portal.app import create_app
from portal.launch import a9
from portal.tests.test_portal import call


class A9HTTP(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=str(Path(self.tmp.name)/'db.sqlite')
        c=db.connect(self.path,webhook=True,reports=True,notifications=True)
        auth.set_password(c,'fixture','fixture-local-only-password')
        c.execute("INSERT INTO projects(slug,name,repo,description,plan_json,created) VALUES(?,?,?,?,?,?)",
                  ('demo-project','Fixture','example/project','safe','{"packages":[]}',time.time()))
        c.close()
        self.github_calls=[]
        def fake(url,token='',etag=None):
            self.github_calls.append(url)
            if '/git/trees/' in url:
                return {'truncated':False,'tree':[{'type':'blob','path':'docs/test.md','size':100},
                              {'type':'tree','path':'docs'},{'type':'blob','path':'assets/test.png','size':5}]},None
            if '/contents/' in url:
                return {'encoding':'base64','content':'IyMg0J/RgNC40L3Rj9GC0L4KLSDQn9GA0LjQvdGP0YLQviDRgNC10YjQtdC90LjQtSAx'},None
            raise ValueError('unknown')
        self.fake=fake
        self.app=create_app(self.path,base='/createportal',secure_cookie=False,ops_enabled=True,
                            reports_enabled=True,webhook_enabled=True,notifications_enabled=True,
                            github_api=fake,memory_root=None)
        login=call(self.app,'POST','/createportal/api/login',{'username':'fixture','password':'fixture-local-only-password'})
        self.cookie=login['headers']['Set-Cookie'].split(';')[0]
        self.csrf=login['json']['csrf']
    def tearDown(self):
        self.app.close();self.tmp.cleanup()
    def req(self,method,path,body=None,authenticated=True,csrf=True):
        url=urllib.parse.urlsplit(path)
        raw=json.dumps(body).encode() if body is not None else b''
        info={}
        path=url.path
        if not path.startswith('/createportal/'):
            path='/createportal'+path
        env={'REQUEST_METHOD':method,'PATH_INFO':path,'QUERY_STRING':url.query,
             'wsgi.input':io.BytesIO(raw),'CONTENT_LENGTH':str(len(raw)),
             'REMOTE_ADDR':'10.0.0.1','HTTP_COOKIE':self.cookie if authenticated else '',
             'HTTP_X_CSRF_TOKEN':self.csrf if csrf else ''}
        def start(status,headers):
            info['status']=int(status.split()[0])
            info['headers']=dict(headers)
        result=b''.join(self.app(env,start))
        info['body']=result
        try:info['json']=json.loads(result)
        except (UnicodeError,ValueError):info['json']=None
        return info
    def test_context_auth_and_length(self):
        self.assertEqual(self.req('GET','/api/projects/demo-project/context',authenticated=False)['status'],401)
        r=self.req('GET','/api/projects/demo-project/context?role=director')
        self.assertEqual(r['status'],200)
        self.assertLessEqual(len(r['json']['text']),6000)
    def test_csrf(self):
        self.assertEqual(self.req('POST','/api/projects/demo-project/decisions',{'title':'Title','text':'Text'},csrf=False)['status'],403)
        self.assertEqual(self.req('POST','/api/projects/demo-project/context-link',{},csrf=False)['status'],403)
    def test_public_link(self):
        resp=self.req('POST','/api/projects/demo-project/context-link',{'role':'director'})
        self.assertEqual(resp['status'],200)
        token=resp['json']['token']
        link=resp['json']['url']
        self.assertEqual(self.req('GET',link,authenticated=False)['status'],200)
        self.assertIn('text/plain',self.req('GET',link,authenticated=False)['headers']['Content-Type'])
        self.assertNotIn(token,Path(self.path).read_bytes().decode('utf-8','ignore'))
        stored=db.connect(self.path,webhook=True,reports=True,notifications=True)
        self.assertTrue(stored.execute('SELECT token_hash FROM context_links WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone())
        stored.close()
        self.assertEqual(self.req('POST','/api/projects/demo-project/context-link',{'revoke':token})['status'],200)
        self.assertEqual(self.req('GET',link,authenticated=False)['status'],404)
    def test_expiration(self):
        r=self.req('POST','/api/projects/demo-project/context-link',{})
        c=db.connect(self.path,webhook=True,reports=True,notifications=True)
        c.execute('UPDATE context_links SET expires=? WHERE token_hash=?',(time.time()-1,hashlib.sha256(r['json']['token'].encode()).hexdigest()))
        c.close()
        self.assertEqual(self.req('GET',r['json']['url'],authenticated=False)['status'],404)
    def test_decision_post(self):
        path='/api/projects/demo-project/decisions'
        self.assertEqual(self.req('POST',path,{'title':'Первое решение','text':'Включаем память'})['status'],200)
        r=self.req('GET',path)
        self.assertTrue(any('Включаем память' in d['text'] for d in r['json']['decisions']))
    def test_repo_tree_stub(self):
        r=self.req('GET','/api/projects/demo-project/repo-map')
        self.assertEqual(r['status'],200)
        self.assertTrue(any(i['path']=='docs/test.md' for i in r['json']['items']))
        self.assertFalse(any(i['path'].endswith('.png') for i in r['json']['items']))
    def test_repo_cache(self):
        self.req('GET','/api/projects/demo-project/repo-map')
        before=len(self.github_calls)
        self.req('GET','/api/projects/demo-project/repo-map')
        self.assertEqual(len(self.github_calls),before)
    def test_disabled(self):
        self.app.close()
        self.app=create_app(self.path,base='/createportal',secure_cookie=False,ops_enabled=True,
                            reports_enabled=True,webhook_enabled=True,notifications_enabled=True,
                            memory_enabled=False)
        self.assertEqual(self.req('GET','/api/projects/demo-project/context')['status'],404)
    def test_invalid(self):
        for suffix in ('?role=bogus','?max=10','?max=6001'):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.req('GET','/api/projects/demo-project/context'+suffix)['status'],400)
    def test_search_stem(self):
        r=self.req('GET','/api/projects/demo-project/search?q=строительство')
        self.assertEqual(r['status'],200)
    def test_link_unauthorized_create(self):
        self.assertEqual(self.req('POST','/api/projects/demo-project/context-link',{},authenticated=False)['status'],401)
    def test_link_tampering(self):
        created=self.req('POST','/api/projects/demo-project/context-link',{})
        path=created['json']['url']
        self.assertEqual(self.req('GET',path[:-1]+'0',authenticated=False)['status'],404)

    def test_ten_link_reads(self):
        created=self.req('POST','/api/projects/demo-project/context-link',{})
        for _ in range(10):
            self.assertEqual(self.req('GET',created['json']['url'],authenticated=False)['status'],200)
        self.assertEqual(self.req('GET',created['json']['url'],authenticated=False)['status'],404)

    def test_readonly_public(self):
        created=self.req('POST','/api/projects/demo-project/context-link',{})
        self.assertEqual(self.req('POST',created['json']['url'],{},authenticated=False)['status'],404)

    def test_wrong_project_revoke(self):
        created=self.req('POST','/api/projects/demo-project/context-link',{})
        conn=db.connect(self.path,webhook=True,reports=True,notifications=True)
        conn.execute("INSERT INTO projects(slug,name,repo,created) VALUES('other-project','Other','example/other',1)")
        conn.close()
        self.assertEqual(self.req('POST','/api/projects/other-project/context-link',{'revoke':created['json']['token']})['status'],200)
        self.assertEqual(self.req('GET',created['json']['url'],authenticated=False)['status'],200)

    def test_public_no_cookies(self):
        created=self.req('POST','/api/projects/demo-project/context-link',{})
        self.assertEqual(self.req('GET',created['json']['url'],authenticated=False)['status'],200)

    def test_budget_boundaries(self):
        for max_chars in ('200','6000'):
            with self.subTest(max_chars=max_chars):
                r=self.req('GET','/api/projects/demo-project/context?max='+max_chars)
                self.assertEqual(r['status'],200)
                self.assertLessEqual(len(r['json']['text']),int(max_chars))

    def test_max_non_numeric(self):
        self.assertEqual(self.req('GET','/api/projects/demo-project/context?max=invalid')['status'],400)

    def test_invalid_kinds(self):
        for suffix in ('q=x','q=abc&kind=unsupported'):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.req('GET','/api/projects/demo-project/search?'+suffix)['status'],400)

    def test_invalid_decision(self):
        cases=[{}, {'title':'x','text':'okay'}, {'title':'Good','text':12},
               {'title':'Good','text':'x'*701}, {'title':'Good','text':'ok','extra':True}]
        for data in cases:
            with self.subTest(data=str(data)[:40]):
                self.assertEqual(self.req('POST','/api/projects/demo-project/decisions',data)['status'],400)

    def test_duplicate_decision(self):
        path='/api/projects/demo-project/decisions'
        data={'title':'Same decision','text':'Same body'}
        self.assertTrue(self.req('POST',path,data)['json']['added'])
        self.assertFalse(self.req('POST',path,data)['json']['added'])

    def test_revoke_input_validation(self):
        for data in ({'revoke':1},{'revoke':'x'*200},{'role':'bad'}, {'unknown':True}):
            with self.subTest(data=str(data)[:40]):
                self.assertEqual(self.req('POST','/api/projects/demo-project/context-link',data)['status'],400)

    def test_secret_decision_redaction(self):
        path='/api/projects/demo-project/decisions'
        self.req('POST',path,{'title':'Token protection','text':'password=private-abc123'})
        r=self.req('GET',path)
        contents=' '.join(v['text'] for v in r['json']['decisions'])
        self.assertNotIn('private-abc123',contents)
        conn=db.connect(self.path,webhook=True,reports=True,notifications=True)
        self.assertNotIn('private-abc123',str(conn.execute('SELECT text FROM project_decisions').fetchall()))
        conn.close()

    def test_search_idea(self):
        self.req('POST','/api/projects/demo-project/ideas',{'text':'Склады и фабрики'})
        r=self.req('GET','/api/projects/demo-project/search?q=склады&kind=idea')
        self.assertEqual(r['status'],200)
        self.assertTrue(any(v['kind']=='idea' for v in r['json']['results']))

    def test_search_report(self):
        conn=db.connect(self.path,webhook=True,reports=True,notifications=True)
        conn.execute("INSERT INTO task_reports(project_slug,pkg_id,body,updated) VALUES(?,?,?,?)",
                     ('demo-project','A9','Особенный результат интеграции',time.time()))
        conn.close()
        r=self.req('GET','/api/projects/demo-project/search?q=особенный&kind=report')
        self.assertTrue(any(v['kind']=='report' for v in r['json']['results']))

    def test_search_lesson(self):
        conn=db.connect(self.path,webhook=True,reports=True,notifications=True)
        conn.execute("INSERT INTO project_lessons(project_slug,content) VALUES(?,?)",
                     ('demo-project','[{"id":"L1","text":"Предупреждение об ошибках"}]'))
        conn.close()
        r=self.req('GET','/api/projects/demo-project/search?q=предупреждение&kind=lesson')
        self.assertTrue(any(v['kind']=='lesson' for v in r['json']['results']))

    def test_memory_repo_map_no_document_body(self):
        self.req('GET','/api/projects/demo-project/search?q=тест&kind=document')
        r=self.req('GET','/api/projects/demo-project/repo-map')
        self.assertTrue(r['json']['items'])
        self.assertFalse(any('doc_text' in i for i in r['json']['items']))

    def test_real_remote_document_index(self):
        r=self.req('GET','/api/projects/demo-project/search?q=принято&kind=document')
        self.assertEqual(r['status'],200)
        self.assertTrue(any(v['id']=='docs/test.md' for v in r['json']['results']))

    def test_bad_repo_no_remote_call(self):
        self.assertEqual(a9.github_tree('../unsafe','main',fetch=self.fake),[])
        self.assertEqual(a9.github_tree('owner/project','../unsafe',fetch=self.fake),[])

    def test_failed_remote_tree_stays_safe(self):
        conn=db.connect(self.path,webhook=True,reports=True,notifications=True)
        self.assertEqual(a9.github_tree('owner/project','main',fetch=lambda *a: (_ for _ in ()).throw(ValueError('offline'))),[])
        conn.close()

    def test_cache_expiry_hour(self):
        self.req('GET','/api/projects/demo-project/repo-map')
        before=len(self.github_calls)
        c=db.connect(self.path,webhook=True,reports=True,notifications=True)
        c.execute("UPDATE repo_map_cache SET updated=? WHERE project_slug=?",(time.time()-3602,'demo-project'))
        c.close()
        self.req('GET','/api/projects/demo-project/repo-map')
        self.assertGreater(len(self.github_calls),before)

    def test_import_approved_decisions(self):
        import base64
        approved='| Код | Решение | Что означает |\n|---|---|---|\n| D-94 | Принята экономика | Поставщик по качеству |'
        def fake(url,*args):
            if '/git/trees/' in url:return {'tree':[],'truncated':False},None
            if 'DECISIONS_APPROVED.md' in url:
                return {'encoding':'base64','content':base64.b64encode(approved.encode()).decode()},None
            raise ValueError('missing')
        c=db.connect(self.path,webhook=True,reports=True,notifications=True)
        a9.sync_decisions(c,'demo-project',None,'example/project','main',fetch=fake)
        rows=a9.decision_list(c,'demo-project')
        self.assertTrue(any(row['id']=='D-94' for row in rows))
        c.close()

    def test_local_clone_identity(self):
        root=Path(self.tmp.name)/'clone'
        (root/'.git').mkdir(parents=True)
        (root/'.git'/'config').write_text('[remote "origin"]\nurl = git@github.com:other/project.git\n')
        self.assertIsNone(a9.root_for(self.app_close_row(),root))

    def app_close_row(self):
        c=db.connect(self.path,webhook=True,reports=True,notifications=True)
        try:
            return c.execute("SELECT * FROM projects WHERE slug='demo-project'").fetchone()
        finally:c.close()
