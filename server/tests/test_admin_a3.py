"""V2-ADM3: isolated PostgreSQL 16 API, security, cache and static UI tests."""
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from server import db
from server.catalog import Catalog, canonical, load_all
from server.catalog.overrides import apply_values, check
from server.game_server import create_app
from server.tests.test_admin_a1 import request

DSN=os.getenv("LUNEX_TEST_DATABASE_URL")
ROOT=Path(__file__).resolve().parents[2]


class AdminA3Static(unittest.TestCase):
    def test_ui_and_filenames(self):
        folder=ROOT/"web"/"admin"
        html=(folder/"index.html").read_text(encoding="utf-8")
        js=(folder/"a3.js").read_text(encoding="utf-8")
        css=(folder/"styles.css").read_text(encoding="utf-8")
        for tab in ("catalog","announcements","releases"):
            self.assertIn('data-tab="'+tab+'"',html)
        for word in ("Каталог","Объявления","Релизы и версии","Предпросмотр",
                     "Применить","Откатить","Экспорт аудита"):
            self.assertIn(word,html+js+(folder/"app.js").read_text())
        self.assertIn("sessionStorage",js+(folder/"app.js").read_text())
        self.assertIn("max-width:600px",css)
        self.assertIn("prefers-color-scheme: light",css)
        self.assertNotIn("http://",html+js+css)
        self.assertNotIn("https://",html+js+css)

    def test_m1_and_allowlist_reject_rewriting_ids(self):
        from server.catalog.overrides import validate_changes
        base=load_all()
        check(base)
        self.assertEqual(len(Catalog().version),64)
        for field in ("name","size.width","id","zones","role","retail_cells"):
            with self.assertRaises(ValueError):
                validate_changes([{"entity":"buildings","id":"field","field":field,"value":1}],base)
        with self.assertRaises(ValueError):
            validate_changes([{"entity":"recipes","id":"mill_flour",
                               "field":"inputs.unknown","value":1}],base)
        with self.assertRaises(ValueError):
            validate_changes([{"entity":"products","id":"bread","field":"reference_price",
                               "value":True}],base)
        invalid=apply_values(base,[{"entity":"recipes","id":"field_grain",
                                    "field":"outputs.grain","value":1}])
        with self.assertRaisesRegex(ValueError,"bread_m1"):
            check(invalid)


@unittest.skipUnless(DSN,"Set LUNEX_TEST_DATABASE_URL to a clean isolated PostgreSQL 16")
class AdminA3Database(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=staticmethod(create_app(DSN))

    @classmethod
    def tearDownClass(cls):
        cls.app.close()

    def admin(self,role):
        suffix=uuid4().hex[:12]
        user="a"+suffix
        password="AdminA3StrictPassword!123"
        reg=request(self.app,"POST","/auth/register",{
            "username":user,"email":user+"@example.test","password":password},
            ip="10.41."+str(int(suffix[:2],16)%240+1)+".1")
        self.assertEqual(reg["status"],201,reg)
        with db.connect(DSN) as conn:
            conn.execute("UPDATE accounts SET role=%s WHERE id=%s",(role,reg["body"]["id"]))
            conn.commit()
        login=request(self.app,"POST","/admin/login",
            {"username":user,"password":password},
            ip="10.42."+str(int(suffix[2:4],16)%240+1)+"."+str(int(suffix[4:6],16)%240+1))
        self.assertEqual(login["status"],200,login)
        return login["body"]["token"],reg["body"]["id"]

    def player(self):
        suffix=uuid4().hex[:12]
        username="p"+suffix
        password="PlayerA3ValidPassword!123"
        reg=request(self.app,"POST","/auth/register",
            {"username":username,"email":username+"@example.test","password":password},
            ip="10.44."+str(int(suffix[2:4],16)%240+1)+".1")
        self.assertEqual(reg["status"],201,reg)
        login=request(self.app,"POST","/auth/login",
            {"username":username,"password":password},
            ip="10.45."+str(int(suffix[2:4],16)%240+1)+".1")
        self.assertEqual(login["status"],200,login)
        return login["body"]["access_token"],reg["body"]["id"]

    def call(self,method,path,token="",data=None,query=""):
        return request(self.app,method,path,data,token=token,query=query)

    def raw(self,path,token,query):
        result={}
        def start(status,headers):
            result["status"]=int(status.split()[0])
            result["headers"]=dict(headers)
        env={"REQUEST_METHOD":"GET","PATH_INFO":path,"QUERY_STRING":query,
             "CONTENT_LENGTH":"2","wsgi.input":io.BytesIO(b"{}"),
             "HTTP_HOST":"localhost:18777","REMOTE_ADDR":"10.71.0.1",
             "HTTP_AUTHORIZATION":"Bearer "+token}
        result["raw"]=b"".join(self.app(env,start))
        return result

    def test_routes_forbidden_and_viewer(self):
        routes=[
            ("GET","/admin/catalog",None),("POST","/admin/catalog/preview",{"changes":[]}),
            ("POST","/admin/catalog/apply",{}),("POST","/admin/catalog/rollback",{}),
            ("GET","/admin/catalog/revisions",None),("GET","/admin/announcements",None),
            ("POST","/admin/announcements",{}),
            ("POST","/admin/announcements/1/deactivate",{}),
            ("GET","/admin/releases",None),("GET","/admin/audit/export",None)]
        for method,path,data in routes:
            self.assertEqual(self.call(method,path,data=data)["status"],403,path)
        self.assertEqual(self.call("GET","/announcements")["status"],401)
        token,_=self.admin("viewer")
        for path in ("/admin/catalog","/admin/catalog/revisions",
                     "/admin/announcements","/admin/releases"):
            response=self.call("GET",path,token)
            self.assertEqual(response["status"],200,(path,response))
        for path in ("/admin/catalog/apply","/admin/catalog/rollback",
                     "/admin/announcements","/admin/announcements/1/deactivate"):
            self.assertEqual(self.call("POST",path,token,{"request_id":"viewer-rejected-1"})["status"],403,path)
        self.assertEqual(self.call("GET","/admin/audit/export",token)["status"],403)

    def test_preview_atomic_revision_cache_idempotent_and_rollback(self):
        token,_=self.admin("owner")
        state=self.call("GET","/admin/catalog",token)["body"]
        old_sha=state["sha"]
        old_rev=state["revision"]
        bread=next(x for x in state["items"]["products"] if x["id"]=="bread")
        price=bread["effective"]["reference_price"]
        changes=[{"entity":"products","id":"bread","field":"reference_price","value":price+1}]
        with db.connect(DSN) as conn:
            n=conn.execute("SELECT count(*) FROM catalog_revisions").fetchone()[0]
        before=self.call("POST","/admin/catalog/preview",token,{"changes":changes})
        self.assertEqual(before["status"],200,before)
        self.assertNotEqual(before["body"]["after_sha"],old_sha)
        with db.connect(DSN) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM catalog_revisions").fetchone()[0],n)
        req="apply-"+uuid4().hex
        payload={"changes":changes,"reason":"A3 regression test","request_id":req}
        try:
            applied=self.call("POST","/admin/catalog/apply",token,payload)
            self.assertEqual(applied["status"],200,applied)
            revision=applied["body"]["revision"]
            self.assertGreater(revision,old_rev)
            retry=self.call("POST","/admin/catalog/apply",token,payload)
            self.assertEqual(retry["status"],200,retry)
            self.assertEqual(retry["body"]["revision"],revision)
            self.assertTrue(retry["body"]["idempotent"])
            changed=dict(payload)
            changed["changes"]=[dict(changes[0],value=price+2)]
            self.assertEqual(self.call("POST","/admin/catalog/apply",token,changed)["status"],409)
            newstate=self.call("GET","/admin/catalog",token)["body"]
            self.assertNotEqual(newstate["sha"],old_sha)
            self.assertEqual(newstate["revision"],revision)
            self.assertTrue(next(x for x in newstate["items"]["products"]
                                 if x["id"]=="bread")["overridden"])
            self.assertEqual(Catalog().version,newstate["sha"])
            from server.enterprises import core
            self.assertEqual(core.catalog().index["products"]["bread"]["reference_price"],price+1)
            self.assertEqual(self.call("GET","/catalog",token)["body"]["version"],newstate["sha"])
            bad=self.call("POST","/admin/catalog/apply",token,{
                "changes":[{"entity":"recipes","id":"field_grain",
                            "field":"outputs.grain","value":1}],
                "reason":"Must reject M1 change","request_id":"m1-"+uuid4().hex})
            self.assertEqual(bad["status"],400,bad)
            self.assertEqual(self.call("GET","/admin/catalog",token)["body"]["revision"],revision)
        finally:
            back=self.call("POST","/admin/catalog/rollback",token,{
                "revision":old_rev,"reason":"Restore original for test","request_id":"rollback-"+uuid4().hex})
            self.assertEqual(back["status"],200,back)
            restored=self.call("GET","/admin/catalog",token)["body"]
            self.assertEqual(restored["sha"],old_sha)
            self.assertEqual(Catalog().version,old_sha)

    def test_invalid_changes_and_over_budget(self):
        token,_=self.admin("admin")
        bad=[
            {"entity":"buildings","id":"field","field":"build_cost","value":-1},
            {"entity":"buildings","id":"field","field":"build_days","value":0},
            {"entity":"buildings","id":"field","field":"jobs","value":10000000},
            {"entity":"products","id":"bread","field":"reference_price","value":True},
            {"entity":"buildings","id":"field","field":"name","value":2},
            {"entity":"recipes","id":"mill_flour","field":"inputs.nonexistent","value":10},
            {"entity":"buildings","id":"field","field":"size.width","value":1},
            {"entity":"buildings","id":"field","field":"build_cost","value":300000}
        ]
        for item in bad:
            result=self.call("POST","/admin/catalog/preview",token,{"changes":[item]})
            self.assertEqual(result["status"],400,(item,result))
        self.assertEqual(self.call("POST","/admin/catalog/preview",token,
            {"changes":[{"entity":"products","id":"bread",
                         "field":"reference_price","value":0}]})["status"],200)

    def test_announcements_windows_city_and_public_safety(self):
        token,_=self.admin("admin")
        player,account=self.player()
        from server.world.core import CITIES
        cities=list(CITIES)
        own_city,other= cities[0],cities[1]
        with db.connect(DSN) as conn:
            num=int(uuid4().hex[:10],16)
            conn.execute("""INSERT INTO world_parcels
                (px,py,city_id,owner_kind,owner_ref)
                VALUES(%s,%s,%s,'player',%s)""",(num,num,own_city,str(account)))
            conn.commit()
        start=(datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat()
        end=(datetime.now(timezone.utc)+timedelta(hours=4)).isoformat()
        ids=[]
        for city in (None,own_city,other):
            payload={"title":"Событие A3","body":"Важная новость, безопасный текст.",
                     "level":"info","city_id":city,"starts_at":start,"ends_at":end,
                     "request_id":"announce-"+uuid4().hex}
            created=self.call("POST","/admin/announcements",token,payload)
            self.assertEqual(created["status"],201,created)
            ids.append(created["body"]["id"])
            retry=self.call("POST","/admin/announcements",token,payload)
            self.assertEqual((retry["status"],retry["body"]["id"]),(200,ids[-1]))
        hidden=self.call("POST","/admin/announcements",token,{
            "title":"Завтра","body":"Пока не показывать","level":"warn","city_id":None,
            "starts_at":(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),
            "ends_at":(datetime.now(timezone.utc)+timedelta(days=2)).isoformat(),
            "request_id":"future-"+uuid4().hex})
        self.assertEqual(hidden["status"],201,hidden)
        result=self.call("GET","/announcements",player)
        self.assertEqual(result["status"],200,result)
        visible={x["id"] for x in result["body"]["items"]}
        self.assertTrue({ids[0],ids[1]}.issubset(visible))
        self.assertNotIn(ids[2],visible)
        self.assertNotIn(hidden["body"]["id"],visible)
        for item in result["body"]["items"]:
            self.assertTrue(set(item)<= {"id","title","body","level","city_id","starts_at","ends_at"})
        deact=self.call("POST",f"/admin/announcements/{ids[0]}/deactivate",token,
                        {"request_id":"deactivate-"+uuid4().hex})
        self.assertEqual(deact["status"],200,deact)
        self.assertNotIn(ids[0],{x["id"] for x in self.call("GET","/announcements",player)["body"]["items"]})
        self.assertEqual(self.call("POST","/admin/announcements",token,{
            "title":"<script>","body":"unsafe","level":"warn","starts_at":start,
            "ends_at":end,"request_id":"invalid-"+uuid4().hex})["status"],400)

    def test_audit_export_real_headers_csv_injection_limit_redaction(self):
        token,_=self.admin("owner")
        with db.connect(DSN) as conn:
            conn.execute("""INSERT INTO audit(actor,actor_role,action,payload)
                VALUES(%s,'admin','formula.a3',%s::jsonb)""",
                ("=HYPERLINK(1,2)",json.dumps({"password":"DO_NOT_EXPORT_123","email":"secret@example.test"})))
            conn.execute("""INSERT INTO audit(actor,actor_role,action,payload)
                SELECT 'a3_test','admin','bulk.a3','{}'::jsonb
                FROM generate_series(1,10004)""")
            conn.commit()
        csv_response=self.raw("/admin/audit/export",token,"format=csv&action=formula.a3")
        self.assertEqual(csv_response["status"],200,csv_response)
        self.assertIn("text/csv",csv_response["headers"]["Content-Type"])
        self.assertIn("attachment",csv_response["headers"]["Content-Disposition"])
        csv_text=csv_response["raw"].decode("utf-8-sig")
        self.assertIn("'=HYPERLINK",csv_text)
        for secret in ("DO_NOT_EXPORT_123","secret@example.test","password","token_hash","email"):
            self.assertNotIn(secret,csv_text)
        all_json=self.raw("/admin/audit/export",token,"format=json&action=bulk.a3")
        self.assertEqual(all_json["status"],200)
        self.assertIn("application/json",all_json["headers"]["Content-Type"])
        self.assertEqual(json.loads(all_json["raw"])["count"],10000)
        self.assertEqual(self.raw("/admin/audit/export",token,"format=x")["status"],400)

    def test_releases_empty_and_safe_supplied_file(self):
        token,_=self.admin("viewer")
        with patch.dict(os.environ,{"LUNEX_RELEASE_META_DIR":""}):
            empty=self.call("GET","/admin/releases",token)
            self.assertEqual(empty["status"],200,empty)
            self.assertIsNone(empty["body"]["release"])
            self.assertTrue(empty["body"]["release_note"])
        with tempfile.TemporaryDirectory(prefix="a3-release-test-") as folder:
            Path(folder,"latest.json").write_text(json.dumps({
                "version_name":"0.1.1","size":1234,"sha256":"a"*64,
                "previous":"0.1.0","secret":"NOT_IN_RESPONSE"}))
            with patch.dict(os.environ,{"LUNEX_RELEASE_META_DIR":folder}):
                data=self.call("GET","/admin/releases",token)
            self.assertEqual(data["status"],200,data)
            self.assertEqual(data["body"]["release"]["version_name"],"0.1.1")
            self.assertNotIn("secret",json.dumps(data["body"]))
            self.assertIn("flags",data["body"])
            self.assertIn("migrations",data["body"])
            self.assertIn("sha",data["body"]["catalog"])
