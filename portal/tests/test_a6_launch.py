"""A6 wizard: input validation, authenticated routes and schema upgrades."""
import json
import tempfile
import unittest
from pathlib import Path

from portal import auth, bootstrap, db, launch
from portal.app import create_app
from portal.tests.test_portal import PW, call

BASE = '/createportal'


class A6Parser(unittest.TestCase):
    def test_valid_variants(self):
        for raw in ('owner/repo', 'owner/repo/', 'owner/repo.git', 'owner/repo/tree/main',
                    'owner/repo/blob/main/file', 'https://github.com/owner/repo',
                    'https://github.com/owner/repo/', 'https://github.com/owner/repo.git',
                    'https://github.com/owner/repo/tree/main/docs', 'OWNER/Repo-1'):
            with self.subTest(raw=raw):
                self.assertEqual(launch.normalize_repo(raw), 'OWNER/Repo-1' if raw=='OWNER/Repo-1' else 'owner/repo')

    def test_invalid_variants(self):
        for raw in ('', 'repo', '/owner/repo', 'https://github.com.evil.test/o/r',
                    'http://github.com/o/r', 'https://evil.test/o/r', 'https://user:pass@github.com/o/r',
                    'https://github.com:444/o/r', 'https://github.com/o/r?access_token=x',
                    'https://github.com/o/r#anchor', 'https://github.com/o/../r',
                    'https://github.com/o/%2e%2e', 'o/r\nINJECT', 'o/r\\hack',
                    '<script>/repo', '../repo', 'owner/..', 'owner/.', 'owner/repo//tail',
                    'owner/repo/../../secret', 'owner/ ', 'file:///o/r', 'ssh://github.com/o/r',
                    'owner/repo'+'x'*501, 0, None, {}, ' owner/repo '):
            with self.subTest(raw=raw):
                with self.assertRaises((ValueError, TypeError)):
                    launch.normalize_repo(raw)

    def test_prompt_is_not_recursive_template(self):
        p = launch.render_prompt('My {wish}', 'own/repo', 'Test {name} {repo} {{().__class__}}')
        self.assertIn('Test {name} {repo}', p)
        self.assertIn('My {wish}', p)
        self.assertIn('own/repo', p)
        self.assertIn('python tools/work_plan.py --plan docs/work_plan.json check', p)
        self.assertIn('pull request', p)

    def test_template_is_from_file(self):
        template = launch.SOURCE.read_text(encoding='utf-8')
        for key in ('{name}', '{repo}', '{wish}', '{plan_path}'):
            self.assertIn(key, template)
        self.assertEqual(launch.render_prompt('N','o/r','W'),template.replace('{name}','N').replace('{repo}','o/r').replace('{wish}','W').replace('{plan_path}',launch.DEFAULT_PLAN_PATH))

    def test_steps_empty_plan(self):
        steps=launch.steps(None)
        self.assertEqual(len(steps),4)
        self.assertTrue(steps[0]['current'])
        self.assertFalse(any(s['done'] for s in steps))

    def test_steps_with_no_tasks(self):
        steps=launch.steps(json.dumps({'packages': []}))
        self.assertTrue(steps[3]['done'])

    def test_steps_with_tasks(self):
        steps=launch.steps(json.dumps({'packages': [{'id':'A1'}]}))
        self.assertTrue(steps[3]['done'])


class A6API(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=str(Path(self.tmp.name)/'portal.sqlite')
        c=db.connect(self.path)
        auth.set_password(c,'owner',PW)
        c.close()
        self.app=create_app(self.path,base=BASE,launch_enabled=True,secure_cookie=False)
        login=self.req('POST','/api/login',{'username':'owner','password':PW})
        self.assertEqual(login['status'],200,login)
        self.cookie=login['headers']['Set-Cookie'].split(';')[0]
        self.csrf=login['json']['csrf']

    def tearDown(self):
        self.app.close()
        self.tmp.cleanup()

    def req(self,method,path,body=None,cookie=None,csrf=None):
        return call(self.app,method,BASE+path,body,self.cookie if cookie is None and hasattr(self,'cookie') else (cookie or ''),
                    self.csrf if csrf is None and hasattr(self,'csrf') else (csrf or ''))

    def create(self,**updates):
        body={'slug':'new-proj','name':'Волшебная Уфа','repo':'https://github.com/owner/repo.git',
              'description':'Коротко','wish':'Мир на четыре игрока'}
        body.update(updates)
        return self.req('POST','/api/projects',body)

    def test_create_and_launch(self):
        self.assertEqual(self.create()['status'],201)
        response=self.req('GET','/api/projects/new-proj/launch')
        self.assertEqual(response['status'],200)
        data=response['json']
        for value in ('Волшебная Уфа','owner/repo','Мир на четыре игрока','docs/work_plan.json'):
            self.assertIn(value,data['prompt'])
        self.assertFalse(data['has_plan'])
        self.assertEqual(len(data['steps']),4)
        self.assertTrue(data['steps'][0]['current'])

    def test_wish_separate_and_limit(self):
        self.assertEqual(self.create(wish='q'*4000)['status'],201)
        c=db.connect(self.path,webhook=True,reports=True,notifications=True)
        r=c.execute('SELECT wish,description FROM projects WHERE slug=?',('new-proj',)).fetchone()
        self.assertEqual(len(r['wish']),4000)
        self.assertEqual(r['description'],'Коротко')
        c.close()

    def test_wish_too_long(self):
        self.assertEqual(self.create(wish='w'*4001)['status'],400)

    def test_invalid_repo(self):
        for value in ('https://evil.test/o/r','owner/../repo','http://github.com/o/r','owner/repo?token=secret','owner/repo\nX'):
            with self.subTest(value=value):
                self.assertEqual(self.create(repo=value)['status'],400)

    def test_types(self):
        for field,value in [('wish',None),('repo',5),('name',[]),('slug',True),('description',{})]:
            with self.subTest(field=field):
                self.assertEqual(self.create(**{field:value})['status'],400)

    def test_empty_token_does_not_block(self):
        self.assertEqual(self.create()['status'],201)

    def test_check_failure_does_not_block(self):
        self.app.close()
        self.app=create_app(self.path,base=BASE,launch_enabled=True,launch_check_repo=lambda r: (_ for _ in ()).throw(TimeoutError()))
        self.assertEqual(self.create()['status'],201)

    def test_repository_exists_callback_advisory(self):
        self.app.close()
        self.app=create_app(self.path,base=BASE,launch_enabled=True,launch_check_repo=lambda r: False)
        response=self.create()
        self.assertEqual(response['status'],201)
        self.assertIs(response['json']['repo_visible'],False)

    def test_csrf_post(self):
        self.assertEqual(self.req('POST','/api/projects',{'slug':'new-proj','name':'New'},csrf='bad')['status'],403)

    def test_login_required(self):
        self.assertEqual(self.req('GET','/api/projects/new-proj/launch',cookie='invalid')['status'],401)
        self.assertEqual(self.req('GET','/api/portal-dev-guide',cookie='invalid')['status'],401)

    def test_step_complete(self):
        self.create()
        self.assertEqual(self.req('POST','/api/projects/new-proj/launch-step',{'number':1,'done':True})['status'],200)
        steps=self.req('GET','/api/projects/new-proj/launch')['json']['steps']
        self.assertTrue(steps[0]['done'])
        self.assertTrue(steps[1]['current'])

    def test_step_invalid(self):
        self.create()
        for value in (0,4,'1',True,None):
            with self.subTest(value=value):
                self.assertEqual(self.req('POST','/api/projects/new-proj/launch-step',{'number':value,'done':True})['status'],400)

    def test_step_csrf(self):
        self.create()
        self.assertEqual(self.req('POST','/api/projects/new-proj/launch-step',{'number':1,'done':True},csrf='invalid')['status'],403)

    def test_step_cannot_mark_sync(self):
        self.create()
        self.assertEqual(self.req('POST','/api/projects/new-proj/launch-step',{'number':4,'done':True})['status'],400)

    def test_dev_guide_exact(self):
        self.assertEqual(self.req('GET','/api/portal-dev-guide')['json']['markdown'],
                         (bootstrap.TPL/'PORTAL_DEV_GUIDE.md').read_text(encoding='utf-8'))

    def test_skeleton_guide_matches(self):
        files=bootstrap.files_for('X','x/y','desc')
        self.assertEqual(files['docs/PORTAL_DEV_GUIDE.md'],(bootstrap.TPL/'PORTAL_DEV_GUIDE.md').read_text(encoding='utf-8'))

    def test_duplicate(self):
        self.assertEqual(self.create()['status'],201)
        self.assertEqual(self.create()['status'],409)

    def test_migration_from_existing_project(self):
        c=db.connect(self.path,webhook=True,reports=True,notifications=True)
        c.execute("INSERT INTO projects(slug,name,repo,description,created) VALUES(?,?,?,?,?)",('existing-project','Existing','owner/existing','Legacy',1))
        c.close()
        read=self.req('GET','/api/projects/existing-project/launch')
        self.assertEqual(read['status'],200)
        self.assertIn('Existing',read['json']['prompt'])
        self.assertIn('(уточнить при интервью)',read['json']['prompt'])

    def test_plan_sync_marks_only_step_four(self):
        self.create()
        c=db.connect(self.path,webhook=True,reports=True,notifications=True)
        c.execute("UPDATE projects SET plan_json=? WHERE slug=?",(json.dumps({'packages':[{'id':'A1'}]}),'new-proj'))
        c.close()
        data=self.req('GET','/api/projects/new-proj/launch')['json']
        self.assertTrue(data['has_tasks'])
        self.assertEqual([s['done'] for s in data['steps']],[False,False,False,True])

    def test_no_plan_missing_data_never_executes_code(self):
        malicious='{__import__("os").system("false")}\n{wish}'
        self.assertEqual(self.create(wish=malicious)['status'],201)
        actual=self.req('GET','/api/projects/new-proj/launch')['json']['prompt']
        self.assertIn(malicious,actual)

    def test_missing_project(self):
        self.assertEqual(self.req('GET','/api/projects/missing-launch/launch')['status'],404)

    def test_legacy_routes(self):
        self.create()
        self.assertEqual(self.req('GET','/api/projects/new-proj/bootstrap')['status'],200)
        self.assertEqual(self.req('GET','/api/projects/new-proj/bootstrap.zip')['status'],200)


if __name__=='__main__':unittest.main()

class A6Addon(unittest.TestCase):
    """Additional A6 requirement: safe plan path, sync URL and lifecycle."""
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.dbfile=str(Path(self.tmp.name)/'a6-path.sqlite')
        conn=db.connect(self.dbfile);auth.set_password(conn,'owner',PW);conn.close()
        self.calls=[]
        def fake(url,token):
            self.calls.append(url)
            return json.dumps(bootstrap.STARTER_PLAN)
        self.app=create_app(self.dbfile,base=BASE,launch_enabled=True,fetch=fake)
        r=call(self.app,'POST',BASE+'/api/login',{'username':'owner','password':PW})
        self.cookie=r['headers']['Set-Cookie'].split(';')[0]
        self.csrf=r['json']['csrf']
    def tearDown(self):
        self.app.close();self.tmp.cleanup()
    def request(self,method,path,body=None,csrf=None,cookie=None):
        return call(self.app,method,BASE+path,body,self.cookie if cookie is None else cookie,self.csrf if csrf is None else csrf)
    def create(self,**kw):
        data={'slug':'new-demo','name':'Demo','repo':'owner/demo','wish':'Plan'}
        data.update(kw)
        return self.request('POST','/api/projects',data)
    def test_default_path(self):
        self.assertEqual(self.create()['status'],201)
        self.assertEqual(self.request('GET','/api/projects/new-demo/plan-settings')['json']['plan_path'],'docs/work_plan.json')
        self.assertEqual(self.request('GET','/api/projects/new-demo')['json']['project']['plan_path'],'docs/work_plan.json')
    def test_alternative_path_create(self):
        created=self.create(plan_path='docs/portal/work_plan.json')
        self.assertEqual(created['status'],201)
        self.assertEqual(created['json']['plan_path'],'docs/portal/work_plan.json')
        launch_data=self.request('GET','/api/projects/new-demo/launch')['json']
        self.assertEqual(launch_data['plan_path'],'docs/portal/work_plan.json')
        self.assertIn('python tools/work_plan.py --plan docs/portal/work_plan.json check',launch_data['prompt'])
    def test_alternative_path_sync(self):
        self.create(plan_path='docs/portal/work_plan.json')
        self.assertEqual(self.request('POST','/api/projects/new-demo/sync',{})['status'],200)
        self.assertTrue(self.calls[0].endswith('/contents/docs/portal/work_plan.json'))
    def test_default_path_sync(self):
        self.create()
        self.assertEqual(self.request('POST','/api/projects/new-demo/sync',{})['status'],200)
        self.assertTrue(self.calls[0].endswith('/contents/docs/work_plan.json'))
    def test_settings_update_changes_sync(self):
        self.create()
        data={'plan_path':'docs/portal/work_plan.json'}
        self.assertEqual(self.request('POST','/api/projects/new-demo/plan-settings',data)['status'],200)
        self.assertEqual(self.request('POST','/api/projects/new-demo/sync',{})['status'],200)
        self.assertTrue(self.calls[0].endswith('/contents/docs/portal/work_plan.json'))
    def test_invalid_paths_at_create(self):
        for path in ('../work_plan.json','/docs/work_plan.json','docs//work_plan.json','docs/../../etc/passwd',
                     'https://evil.test/file','docs/work_plan.json?x=1','docs/%2e%2e/work_plan.json', '',None,False,[],{}):
            with self.subTest(path=path):
                self.assertEqual(self.create(plan_path=path)['status'],400)
    def test_invalid_update_preserves_existing_path(self):
        self.create()
        for path in ('docs/../work_plan.json','../../etc/shadow','docs/progress.json',3):
            self.assertEqual(self.request('POST','/api/projects/new-demo/plan-settings',{'plan_path':path})['status'],400)
        self.assertEqual(self.request('GET','/api/projects/new-demo/plan-settings')['json']['plan_path'],'docs/work_plan.json')
    def test_csrf_and_auth_on_settings(self):
        self.create()
        path='/api/projects/new-demo/plan-settings'
        self.assertEqual(self.request('POST',path,{'plan_path':'docs/portal/work_plan.json'},csrf='incorrect')['status'],403)
        self.assertEqual(self.request('GET',path,cookie='invalid')['status'],401)
    def test_existing_project_migration_default(self):
        self.create()
        self.assertEqual(self.request('GET','/api/projects/new-demo')['json']['project']['plan_path'],'docs/work_plan.json')

class A6PlanPolling(unittest.TestCase):
    def setUp(self):
        from portal.launch.plan_poll import poll_plans
        self.poll_plans=poll_plans
        self.tmp=tempfile.TemporaryDirectory()
        self.file=str(Path(self.tmp.name)/'poll-path.sqlite')
        self.conn=db.connect(self.file,webhook=True)
        self.conn.execute("INSERT INTO projects(slug,name,repo,plan_path,created) VALUES(?,?,?,?,?)",
                          ('test-plan','Test','owner/repo','docs/portal/work_plan.json',0))
        self.urls=[]
    def tearDown(self):
        self.conn.close();self.tmp.cleanup()
    def fake(self,url,token):
        self.urls.append(url)
        return json.dumps(bootstrap.STARTER_PLAN)
    def test_poll_reads_configured_path(self):
        self.assertEqual(self.poll_plans(self.conn,now=1000,fetch=self.fake),1)
        self.assertTrue(self.urls[0].endswith('/contents/docs/portal/work_plan.json'))
        self.assertTrue(self.conn.execute("SELECT plan_json FROM projects WHERE slug='test-plan'").fetchone()[0])
    def test_poll_respects_interval(self):
        self.poll_plans(self.conn,now=1000,fetch=self.fake)
        self.assertEqual(self.poll_plans(self.conn,now=1100,fetch=self.fake),0)
        self.assertEqual(self.poll_plans(self.conn,now=1300,fetch=self.fake),1)
    def test_poll_failure_preserves_old_plan(self):
        self.poll_plans(self.conn,now=1000,fetch=self.fake)
        old=self.conn.execute("SELECT plan_json FROM projects WHERE slug='test-plan'").fetchone()[0]
        self.assertEqual(self.poll_plans(self.conn,now=1600,fetch=lambda *a: (_ for _ in ()).throw(OSError('offline'))),1)
        self.assertEqual(self.conn.execute("SELECT plan_json FROM projects WHERE slug='test-plan'").fetchone()[0],old)
        self.assertEqual(self.conn.execute("SELECT last_state FROM project_plan_poll WHERE project_slug='test-plan'").fetchone()[0],'error')
    def test_poll_invalid_json_preserves_state(self):
        self.assertEqual(self.poll_plans(self.conn,now=1000,fetch=lambda *a:'not-json'),1)
        self.assertIsNone(self.conn.execute("SELECT plan_json FROM projects WHERE slug='test-plan'").fetchone()[0])
    def test_poll_mode_disabled(self):
        self.conn.execute("UPDATE projects SET sync_mode='webhook' WHERE slug='test-plan'")
        self.assertEqual(self.poll_plans(self.conn,now=1000,fetch=self.fake),0)
        self.assertEqual(self.urls,[])
    def test_poll_new_path_after_change(self):
        self.poll_plans(self.conn,now=1000,fetch=self.fake)
        self.conn.execute("UPDATE projects SET plan_path='docs/work_plan.json' WHERE slug='test-plan'")
        self.poll_plans(self.conn,now=2000,fetch=self.fake)
        self.assertTrue(self.urls[-1].endswith('/contents/docs/work_plan.json'))
    def test_poll_does_not_update_time_for_same_plan(self):
        self.poll_plans(self.conn,now=1000,fetch=self.fake)
        original=self.conn.execute("SELECT plan_updated FROM projects WHERE slug='test-plan'").fetchone()[0]
        self.poll_plans(self.conn,now=2000,fetch=self.fake)
        self.assertEqual(self.conn.execute("SELECT plan_updated FROM projects WHERE slug='test-plan'").fetchone()[0],original)
    def test_poll_invalid_plan_rejected(self):
        self.poll_plans(self.conn,now=1000,fetch=lambda *a:json.dumps({'bad':True}))
        self.assertIsNone(self.conn.execute("SELECT plan_json FROM projects WHERE slug='test-plan'").fetchone()[0])
