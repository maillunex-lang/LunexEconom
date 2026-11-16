"""A7 API, review adapters, input boundaries and safety regression tests."""
import json
import tempfile
import unittest
from pathlib import Path
from portal import db,auth
from portal.app import create_app
from portal.launch import a7
from portal.review import engine, knowledge, library, returns, project_types
from portal.tests.test_portal import call,PW

BASE='/createportal'

class A7API(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=str(Path(self.tmp.name)/'portal.sqlite')
        c=db.connect(self.path);auth.set_password(c,'owner',PW);c.close()
        self.urls=[]
        def fake_json(url,token):
            self.urls.append(url)
            if '/files?' in url:return [{'filename':'server/test.py','additions':2,'deletions':1},{'filename':'server/tests/test_demo.py','additions':5,'deletions':0}]
            return {'state':'open','draft':False,'head':{'sha':'a'*40},'base':{'ref':'main'},'mergeable':True}
        self.app=create_app(self.path,base=BASE,launch_enabled=True,reports_enabled=True,webhook_enabled=True,
                            review_a7_enabled=True,review_fetch_json=fake_json,review_fetch_diff=lambda u,t:'+++ b/server/test.py\n+value=1\n')
        r=call(self.app,'POST',BASE+'/api/login',{'username':'owner','password':PW})
        self.cookie=r['headers']['Set-Cookie'].split(';')[0];self.csrf=r['json']['csrf']
        self.conn=db.connect(self.path,webhook=True,reports=True,notifications=True)
    def tearDown(self):
        self.conn.close();self.app.close();self.tmp.cleanup()
    def req(self,method,path,body=None,csrf=None,cookie=None):
        return call(self.app,method,BASE+path,body,self.cookie if cookie is None else cookie,self.csrf if csrf is None else csrf)
    def create(self,project_type='game'):
        return self.req('POST','/api/projects',{'slug':'demo-project','name':'Demo','repo':'owner/demo','wish':'Make a game','project_type':project_type})
    def test_catalog(self):
        r=self.req('GET','/api/project-types');self.assertEqual(r['status'],200);self.assertEqual(len(r['json']['types']),4)
    def test_templates(self):
        r=self.req('GET','/api/return-templates');self.assertEqual(r['status'],200);self.assertGreater(len(r['json']['templates']),5)
    def test_create_types(self):
        for kind in ('game','bot','web_service','mobile_app'):
            with self.subTest(kind=kind):
                self.assertEqual(self.create(kind)['status'],201)
                self.assertEqual(self.req('GET','/api/projects/demo-project')['json']['project']['project_type'],kind)
                self.conn.execute("DELETE FROM projects WHERE slug='demo-project'")
    def test_invalid_type(self):
        self.assertEqual(self.create('invalid')['status'],400)
    def test_starter(self):
        self.create('bot');r=self.req('GET','/api/projects/demo-project');self.assertEqual(len(r['json']['packages']),2)
    def test_default_merge_disabled(self):
        self.create();r=self.req('GET','/api/projects/demo-project/auto-merge-settings')['json']['settings']
        self.assertFalse(r['auto_merge']);self.assertTrue(r['kill_switch']);self.assertEqual(r['auto_merge_delay_minutes'],10)
    def test_settings(self):
        self.create();data={'auto_merge':True,'kill_switch':False,'auto_merge_delay_minutes':15}
        self.assertEqual(self.req('POST','/api/projects/demo-project/auto-merge-settings',data)['status'],200)
        self.assertEqual(self.req('GET','/api/projects/demo-project/auto-merge-settings')['json']['settings'],data)
    def test_lessons(self):
        self.create();self.assertEqual(self.req('POST','/api/projects/demo-project/lessons',{'text':'Always add integration tests'})['status'],200)
        self.assertEqual(len(self.req('GET','/api/projects/demo-project/lessons')['json']['lessons']),1)
    def test_lessons_prompt(self):
        self.create();self.req('POST','/api/projects/demo-project/lessons',{'text':'Always add integration tests'})
        self.assertIn('Always add integration tests',self.req('GET','/api/projects/demo-project')['json']['packages'][0]['prompt'])
        self.assertIn('Always add integration tests',self.req('GET','/api/projects/demo-project/launch')['json']['prompt'])
    def test_lessons_delete(self):
        self.create();self.req('POST','/api/projects/demo-project/lessons',{'text':'Always add integration tests'})
        self.assertEqual(self.req('DELETE','/api/projects/demo-project/lessons',{'id':'L1'})['status'],200)
        self.assertEqual(self.req('GET','/api/projects/demo-project/lessons')['json']['lessons'],[])
    def test_conflicts(self):
        self.create();r=self.req('GET','/api/projects/demo-project/conflicts');self.assertEqual(r['status'],200);self.assertIn('warnings',r['json'])
    def test_review_without_pr_is_yellow(self):
        self.create();r=self.req('GET','/api/projects/demo-project/tasks/A1/review');self.assertEqual(r['status'],200)
        self.assertEqual(r['json']['traffic_light']['status'],'yellow')
    def test_review_event(self):
        self.create();self.req('GET','/api/projects/demo-project/tasks/A1/review')
        self.assertEqual(self.conn.execute("SELECT count(*) FROM task_review_runs").fetchone()[0],1)
    def test_review_with_pr(self):
        self.create();self.conn.execute("INSERT INTO pr_links(project_slug,pkg_id,pr_number,branch,sha,state,ci_state,updated) VALUES(?,?,?,?,?,?,?,?)",('demo-project','A1',3,'feature/A1','a'*40,'open','success',0))
        r=self.req('GET','/api/projects/demo-project/tasks/A1/review')
        self.assertEqual(r['status'],200);self.assertEqual(len(r['json']['traffic_light']['files']),2)
    def test_return_rejects_secret_note(self):
        self.create();r=self.req('POST','/api/projects/demo-project/tasks/A1/return',{'reasons':['no_tests'],'note':'ghp_'+'A'*40})
        self.assertEqual(r['status'],400)
    def test_return_requires_submitted(self):
        self.create();r=self.req('POST','/api/projects/demo-project/tasks/A1/return',{'reasons':['no_tests'],'note':''})
        self.assertEqual(r['status'],409)
    def test_return_prompt(self):
        self.create();self.conn.execute("INSERT INTO task_state(project_slug,pkg_id,status) VALUES(?,?,?)",('demo-project','A1','submitted'))
        r=self.req('POST','/api/projects/demo-project/tasks/A1/return',{'reasons':['no_tests'],'note':'Add test cases'})
        self.assertEqual(r['status'],200);self.assertIn('Доработка задания A1',r['json']['prompt'])
        self.assertEqual(self.conn.execute("SELECT status FROM task_state WHERE pkg_id='A1'").fetchone()[0],'issued')
    def test_return_suggestions(self):
        self.create();self.conn.execute("INSERT INTO task_returns(project_slug,pkg_id,reasons,created) VALUES(?,?,?,?)",('demo-project','A1','["no_tests","no_tests"]',0))
        self.assertEqual(self.req('GET','/api/projects/demo-project/lessons')['json']['suggestions'][0]['reason'],'no_tests')
    def test_cancel_merge(self):
        self.create();self.conn.execute("INSERT INTO task_auto_merge(project_slug,pkg_id,pr_number,due_at) VALUES(?,?,?,?)",('demo-project','A1',1,100))
        self.assertEqual(self.req('POST','/api/projects/demo-project/tasks/A1/cancel-auto-merge',{})['status'],200)
        self.assertEqual(self.conn.execute('SELECT cancelled FROM task_auto_merge').fetchone()[0],1)
    def test_csrf(self):
        self.create();self.assertEqual(self.req('POST','/api/projects/demo-project/lessons',{'text':'Always test new features'},csrf='bad')['status'],403)
    def test_auth(self):
        self.create();self.assertEqual(self.req('GET','/api/projects/demo-project/lessons',cookie='bad')['status'],401)

# Distinct negative/positive boundary cases: each is an independently reported unittest.
BAD_LESSONS=['','x','abc','seven',' '*20,'abc def','short','x'*401,'x'*1000,'ghp_'+'A'*40,'github_pat_'+'Z'*50,'sk-'+'A'*40,'-----BEGIN PRIVATE KEY-----',"password='"+'A'*20+"'"]
BAD_SETTINGS=[{'auto_merge':1,'kill_switch':False,'auto_merge_delay_minutes':10},
 {'auto_merge':False,'kill_switch':0,'auto_merge_delay_minutes':10},
 {'auto_merge':False,'kill_switch':False,'auto_merge_delay_minutes':9},
 {'auto_merge':False,'kill_switch':False,'auto_merge_delay_minutes':1441},
 {'auto_merge':False,'kill_switch':False,'auto_merge_delay_minutes':'10'},
 {'auto_merge':False,'kill_switch':False,'auto_merge_delay_minutes':None},
 {'auto_merge':False,'kill_switch':False,'auto_merge_delay_minutes':10,'secret':'x'},
 {'auto_merge':False,'kill_switch':False},
 {'auto_merge':False,'kill_switch':False,'auto_merge_delay_minutes':True},
 {'auto_merge':[], 'kill_switch':False,'auto_merge_delay_minutes':10},
 {'auto_merge':False,'kill_switch':False,'auto_merge_delay_minutes':-1}]
BAD_RETURNS=[{'reasons':['bogus'],'note':''},{'reasons':'no_tests','note':''},{'reasons':[],'note':''},
 {'reasons':['no_tests'],'note':3},{'reasons':['no_tests'],'note':'x'*1501},
 {'reasons':[1],'note':''},{'reasons':['no_tests']*10,'note':''},
 {'reasons':['no_tests'],'note':'','extra':'x'},{'note':'hi'},{'reasons':[]},
 {'reasons':{},'note':''}]

def attach_cases():
    for i,text in enumerate(BAD_LESSONS):
        def check(self,text=text):
            self.create();r=self.req('POST','/api/projects/demo-project/lessons',{'text':text});self.assertEqual(r['status'],400)
        setattr(A7API,'test_invalid_lesson_%02d'%i,check)
    for i,data in enumerate(BAD_SETTINGS):
        def check(self,data=data):
            self.create();r=self.req('POST','/api/projects/demo-project/auto-merge-settings',data);self.assertEqual(r['status'],400)
        setattr(A7API,'test_invalid_merge_setting_%02d'%i,check)
    for i,data in enumerate(BAD_RETURNS):
        def check(self,data=data):
            self.create();r=self.req('POST','/api/projects/demo-project/tasks/A1/return',data);self.assertEqual(r['status'],400)
        setattr(A7API,'test_invalid_return_%02d'%i,check)
    for i,kind in enumerate(('invalid','Game','WEB_SERVICE','mobile-app','bot/../../','',None,[],{},12,True)):
        def check(self,kind=kind):
            self.assertEqual(self.create(kind)['status'],400)
        setattr(A7API,'test_invalid_project_type_%02d'%i,check)
attach_cases()

class A7MergeSafety(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'merge.sqlite')
        self.conn=db.connect(self.path,webhook=True,reports=True,notifications=True)
        self.conn.execute("INSERT INTO projects(slug,name,repo,created) VALUES('safe-project','Safe','owner/repo',0)")
        self.conn.execute("INSERT INTO pr_links(project_slug,pkg_id,pr_number,branch,sha,state,ci_state,updated) VALUES('safe-project','A1',7,'feature/A1',?,'open','success',0)",('a'*40,))
        self.conn.execute("INSERT INTO task_state(project_slug,pkg_id,status) VALUES('safe-project','A1','submitted')")
        self.conn.execute("INSERT INTO project_a7_settings(project_slug,auto_merge,auto_merge_delay_minutes,kill_switch) VALUES('safe-project',1,10,0)")
        self.green={'status':'green','checks':[{'id':'checklist','status':'green'}]}
    def tearDown(self):self.conn.close();self.tmp.cleanup()
    def test_schedule_requires_green(self):
        self.assertFalse(a7.schedule(self.conn,'safe-project','A1',{'status':'yellow','checks':[]},1000))
    def test_schedule_delay(self):
        self.assertTrue(a7.schedule(self.conn,'safe-project','A1',self.green,1000))
        self.assertEqual(self.conn.execute('SELECT due_at FROM task_auto_merge').fetchone()[0],1600)
    def test_kill_switch(self):
        self.conn.execute("UPDATE project_a7_settings SET kill_switch=1 WHERE project_slug='safe-project'")
        self.assertFalse(a7.schedule(self.conn,'safe-project','A1',self.green,1000))
    def test_auto_merge_default_disabled(self):
        self.conn.execute("UPDATE project_a7_settings SET auto_merge=0 WHERE project_slug='safe-project'")
        self.assertFalse(a7.schedule(self.conn,'safe-project','A1',self.green,1000))
    def test_cancelled_not_merged(self):
        self.assertTrue(a7.schedule(self.conn,'safe-project','A1',self.green,1000))
        self.conn.execute("UPDATE task_auto_merge SET cancelled=1")
        self.assertEqual(a7.merge_due(self.conn,None,now=2000),0)
    def test_no_token_never_merges(self):
        self.assertTrue(a7.schedule(self.conn,'safe-project','A1',self.green,1000))
        self.assertEqual(a7.merge_due(self.conn,None,now=2000),0)
        self.assertEqual(self.conn.execute('SELECT cancelled FROM task_auto_merge').fetchone()[0],0)
    def test_wrong_token_permissions(self):
        path=Path(self.tmp.name)/'token';path.write_text('not-a-real-token');path.chmod(0o644)
        self.assertTrue(a7.schedule(self.conn,'safe-project','A1',self.green,1000))
        self.assertEqual(a7.merge_due(self.conn,str(path),now=2000),0)
    def test_no_duplicate_schedule(self):
        self.assertTrue(a7.schedule(self.conn,'safe-project','A1',self.green,1000))
        self.assertTrue(a7.schedule(self.conn,'safe-project','A1',self.green,1200))
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM task_auto_merge').fetchone()[0],1)
