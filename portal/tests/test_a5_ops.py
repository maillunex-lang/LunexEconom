import copy
import json
import tempfile
import unittest
from pathlib import Path
from portal import auth, bootstrap, db
from portal.app import create_app
from portal.backup import core, sync
from portal.tests.test_portal import call

class Ops(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=str(Path(self.tmp.name)/"portal.sqlite")
        c=db.connect(self.path);auth.set_password(c,"owner","test-password-for-ops");c.close()
        self.app=create_app(self.path,base="/createportal",ops_enabled=True,webhook_enabled=True,
                            reports_enabled=True,notifications_enabled=True,backup_dir=self.tmp.name,
                            github_api=lambda *a:({"check_runs":[{"status":"completed","conclusion":"success"}],"total_count":1},None))
        r=call(self.app,"POST","/api/login",{"username":"owner","password":"test-password-for-ops"})
        self.cookie=r["headers"]["Set-Cookie"].split(";")[0];self.csrf=r["json"]["csrf"]
        self.req("POST","/api/projects",{"slug":"demo-project","name":"Demo"})
    def tearDown(self):
        self.app.close();self.tmp.cleanup()
    def req(self,method,path,body=None,cookie=None,csrf=None):
        return call(self.app,method,path,body,cookie=self.cookie if cookie is None else cookie,csrf=self.csrf if csrf is None else csrf)
    def test_01_version(self):self.assertEqual(self.req("GET","/api/version")["status"],200)
    def test_02_version_features(self):self.assertTrue(self.req("GET","/api/version")["json"]["features"]["ops"])
    def test_03_today(self):self.assertEqual(self.req("GET","/api/today")["status"],200)
    def test_04_today_empty(self):self.assertEqual(self.req("GET","/api/today")["json"]["queue"],[])
    def test_05_backup(self):self.assertEqual(self.req("POST","/api/backup",{})["status"],200)
    def test_06_backup_latest(self):
        self.req("POST","/api/backup",{})
        self.assertTrue(self.req("GET","/api/backup/latest")["body"].startswith(b"SQLite format 3"))
    def test_07_backup_status(self):
        self.req("POST","/api/backup",{})
        self.assertEqual(len(self.req("GET","/api/backup/status")["json"]["backups"]),1)
    def test_08_backup_auth(self):self.assertEqual(self.req("GET","/api/backup/status",cookie="")["status"],401)
    def test_09_backup_csrf(self):self.assertEqual(self.req("POST","/api/backup",{},csrf="bad")["status"],403)
    def test_10_backup_restore(self):
        self.req("POST","/api/backup",{})
        dest=Path(self.tmp.name)/"restored.sqlite"
        core.restore_backup(core.latest_backup(self.tmp.name),str(dest))
        self.assertTrue(core.verify_backup(str(dest))["ok"])
    def test_11_export(self):self.assertEqual(self.req("GET","/api/projects/demo-project/export")["json"]["format"],core.FORMAT)
    def test_12_export_zip(self):self.assertEqual(self.req("GET","/api/projects/demo-project/export.zip")["body"][:2],b"PK")
    def test_13_import(self):
        data=self.req("GET","/api/projects/demo-project/export")["json"]
        self.assertEqual(self.req("POST","/api/projects/import",{"data":data,"slug":"second-project"})["status"],201)
    def test_14_import_duplicate(self):
        data=self.req("GET","/api/projects/demo-project/export")["json"]
        self.assertEqual(self.req("POST","/api/projects/import",{"data":data})["status"],409)
    def test_15_delete_requires_confirm(self):self.assertEqual(self.req("DELETE","/api/projects/demo-project",{"confirm":"wrong"})["status"],409)
    def test_16_delete(self):self.assertEqual(self.req("DELETE","/api/projects/demo-project",{"confirm":"demo-project"})["status"],200)
    def test_17_delete_audit(self):
        self.req("DELETE","/api/projects/demo-project",{"confirm":"demo-project"})
        self.assertIn("project.delete",str(self.req("GET","/api/audit")["json"]))
    def test_18_delete_csrf(self):self.assertEqual(self.req("DELETE","/api/projects/demo-project",{"confirm":"demo-project"},csrf="bad")["status"],403)
    def test_19_graph_no_plan(self):self.assertEqual(self.req("GET","/api/projects/demo-project/graph")["status"],409)
    def test_20_graph_plan(self):
        self.req("POST","/api/projects/demo-project/plan",{"plan":copy.deepcopy(bootstrap.STARTER_PLAN)})
        self.assertEqual(self.req("GET","/api/projects/demo-project/graph")["status"],200)
    def test_21_search_invalid(self):self.assertEqual(self.req("GET","/api/projects/demo-project/search")["status"],400)
    def test_22_search(self):
        self.req("POST","/api/projects/demo-project/ideas",{"text":"special searchable idea"})
        # call helper doesn't populate query string; verify endpoint availability via path.
        self.assertEqual(self.req("GET","/api/projects/demo-project/search")["status"],400)
    def test_32_share_save(self):
        self.assertEqual(self.req("POST","/api/share",{"slug":"demo-project","title":"Hello"})["status"],201)
    def test_33_share_csrf(self):
        self.assertEqual(self.req("POST","/api/share",{"slug":"demo-project","title":"Hello"},csrf="bad")["status"],403)
    def test_34_share_invalid_project(self):
        self.assertEqual(self.req("POST","/api/share",{"slug":"other-project","title":"Hello"})["status"],404)
    def test_31_search_query(self):
        import io
        self.req("POST","/api/projects/demo-project/ideas",{"text":"needle found here"})
        env={"PATH_INFO":"/api/projects/demo-project/search","QUERY_STRING":"q=needle",
             "REQUEST_METHOD":"GET","wsgi.input":io.BytesIO(b""),"CONTENT_LENGTH":"0","HTTP_COOKIE":self.cookie}
        result={}
        response=json.loads(b"".join(self.app(env,lambda status,headers:result.update(status=status))))
        self.assertEqual(result["status"].split()[0],"200")
        self.assertEqual(response["results"][0]["type"],"idea")
    def test_23_sync_default(self):self.assertEqual(self.req("GET","/api/projects/demo-project/sync-settings")["json"]["sync_mode"],"both")
    def test_24_sync_settings(self):self.assertEqual(self.req("POST","/api/projects/demo-project/sync-settings",{"sync_mode":"polling","poll_minutes":10})["status"],200)
    def test_25_sync_bad_interval(self):self.assertEqual(self.req("POST","/api/projects/demo-project/sync-settings",{"sync_mode":"both","poll_minutes":1})["status"],400)
    def test_26_sync_status(self):self.assertFalse(self.req("GET","/api/projects/demo-project/sync-status")["json"]["webhook_seen"])
    def test_27_import_invalid(self):self.assertEqual(self.req("POST","/api/projects/import",{"data":{}})["status"],409)
    def test_28_backup_reject_body(self):self.assertEqual(self.req("POST","/api/backup",{"bad":True})["status"],400)
    def test_29_share_draft(self):
        # Direct WSGI to include query string.
        import io
        result={}
        env={"PATH_INFO":"/createportal/share","QUERY_STRING":"title=hello&text=world","REQUEST_METHOD":"GET","wsgi.input":io.BytesIO(b""),"CONTENT_LENGTH":"0"}
        data=b"".join(self.app(env,lambda status,headers:result.update(status=status)))
        self.assertEqual(result["status"].split()[0],"200")
        self.assertEqual(json.loads(data)["draft"]["title"],"hello")
    def test_30_feature_off(self):
        app=create_app(str(Path(self.tmp.name)/"disabled.sqlite"))
        try:
            self.assertEqual(call(app,"GET","/api/version")["status"],401)
        finally:app.close()

class Polling(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.conn=db.connect(str(Path(self.tmp.name)/"poll.sqlite"),webhook=True)
        self.conn.execute("INSERT INTO projects(slug,name,repo,branch,created) VALUES('demo-project','Demo','owner/repo','main',0)")
        self.sha="a"*40
        self.calls=[]
        self.pr={"number":1,"merged_at":"2026-01-01","merge_commit_sha":self.sha,
                 "head":{"ref":"v2/A1-test","sha":"b"*40},"base":{"ref":"main"},"title":"A1 done"}
        self.check={"total_count":1,"check_runs":[{"id":1,"status":"completed","conclusion":"success"}]}
    def tearDown(self):self.conn.close();self.tmp.cleanup()
    def fake(self,url,token,etag):
        self.calls.append((url,etag))
        if "/pulls?" in url:return [self.pr],"etag-a"
        if "/check-runs" in url:return self.check,None
        raise AssertionError(url)
    def test_01_default_mode(self):self.assertEqual(self.conn.execute("SELECT sync_mode FROM projects").fetchone()[0],"both")
    def test_02_default_interval(self):self.assertEqual(self.conn.execute("SELECT poll_minutes FROM projects").fetchone()[0],5)
    def test_03_poll_empty_plan(self):self.assertEqual(sync.poll_project(self.conn,"demo-project","",self.fake,1000),1)
    def test_04_poll_dedup(self):
        sync.poll_project(self.conn,"demo-project","",self.fake,1000)
        self.assertEqual(sync.poll_project(self.conn,"demo-project","",self.fake,2000),0)
    def test_05_poll_timestamp(self):
        sync.poll_project(self.conn,"demo-project","",self.fake,1000)
        self.assertEqual(self.conn.execute("SELECT last_poll FROM project_sync").fetchone()[0],1000)
    def test_06_poll_etag(self):
        sync.poll_project(self.conn,"demo-project","",self.fake,1000)
        sync.poll_project(self.conn,"demo-project","",self.fake,2000)
        self.assertEqual([etag for url,etag in self.calls if "/pulls?" in url][-1],"etag-a")
    def test_07_webhook_mode(self):
        self.conn.execute("UPDATE projects SET sync_mode='webhook'")
        self.assertEqual(sync.poll_project(self.conn,"demo-project","",self.fake,1000),0)
    def test_08_invalid_repo(self):
        self.conn.execute("UPDATE projects SET repo='bad repo'")
        self.assertEqual(sync.poll_project(self.conn,"demo-project","",self.fake,1000),0)
    def test_09_no_checks(self):
        self.check={"total_count":0,"check_runs":[]}
        self.assertFalse(sync.complete_checks("owner/repo",self.sha,"",self.fake))
    def test_10_green_checks(self):self.assertTrue(sync.complete_checks("owner/repo",self.sha,"",self.fake))
    def test_11_red_checks(self):
        self.check["check_runs"][0]["conclusion"]="failure"
        self.assertFalse(sync.complete_checks("owner/repo",self.sha,"",self.fake))
    def test_12_pending_checks(self):
        self.check["check_runs"][0]["status"]="in_progress"
        self.assertFalse(sync.complete_checks("owner/repo",self.sha,"",self.fake))
    def test_13_partial_checks(self):
        self.check["total_count"]=2
        self.assertFalse(sync.complete_checks("owner/repo",self.sha,"",self.fake))
    def test_14_invalid_sha(self):self.assertFalse(sync.complete_checks("owner/repo","notsha","",self.fake))
    def test_15_invalid_repo(self):self.assertFalse(sync.complete_checks("bad repo",self.sha,"",self.fake))
    def test_16_fetch_error(self):
        self.assertEqual(sync.poll_project(self.conn,"demo-project","",lambda *a:(_ for _ in ()).throw(ValueError("no")),1000),0)
        self.assertEqual(self.conn.execute("SELECT error FROM project_sync").fetchone()[0],"poll_failed")
    def test_17_poll_closed_only(self):
        self.pr["merged_at"]=None
        self.assertEqual(sync.poll_project(self.conn,"demo-project","",self.fake,1000),0)
    def test_18_poll_wrong_sha(self):
        self.pr["merge_commit_sha"]="invalid"
        self.assertEqual(sync.poll_project(self.conn,"demo-project","",self.fake,1000),0)
    def test_19_poll_empty_list(self):
        self.assertEqual(sync.poll_project(self.conn,"demo-project","",lambda *a:([],None),1000),0)
    def test_21_autoaccept_complete_ci(self):
        plan=copy.deepcopy(bootstrap.STARTER_PLAN)
        self.conn.execute("UPDATE projects SET plan_json=? WHERE slug='demo-project'",(json.dumps(plan),))
        self.conn.execute("INSERT INTO task_state(project_slug,pkg_id,status) VALUES('demo-project','A1','submitted')")
        sync.poll_project(self.conn,"demo-project","",self.fake,1000)
        self.assertEqual(self.conn.execute("SELECT status FROM task_state WHERE pkg_id='A1'").fetchone()[0],"accepted")
    def test_22_no_autoaccept_red_ci(self):
        plan=copy.deepcopy(bootstrap.STARTER_PLAN)
        self.conn.execute("UPDATE projects SET plan_json=? WHERE slug='demo-project'",(json.dumps(plan),))
        self.conn.execute("INSERT INTO task_state(project_slug,pkg_id,status) VALUES('demo-project','A1','submitted')")
        self.check["check_runs"][0]["conclusion"]="failure"
        sync.poll_project(self.conn,"demo-project","",self.fake,1000)
        self.assertEqual(self.conn.execute("SELECT status FROM task_state WHERE pkg_id='A1'").fetchone()[0],"submitted")
    def test_23_no_autoaccept_missing_ci(self):
        plan=copy.deepcopy(bootstrap.STARTER_PLAN)
        self.conn.execute("UPDATE projects SET plan_json=? WHERE slug='demo-project'",(json.dumps(plan),))
        self.conn.execute("INSERT INTO task_state(project_slug,pkg_id,status) VALUES('demo-project','A1','submitted')")
        self.check={"check_runs":[],"total_count":0}
        sync.poll_project(self.conn,"demo-project","",self.fake,1000)
        self.assertEqual(self.conn.execute("SELECT status FROM task_state WHERE pkg_id='A1'").fetchone()[0],"submitted")
    def test_20_poll_invalid_list(self):
        self.assertEqual(sync.poll_project(self.conn,"demo-project","",lambda *a:({},None),1000),0)
