"""Loopback WSGI integration test with real HTTP transport."""
import json
import hmac
import hashlib
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
import http.cookiejar
from pathlib import Path
from wsgiref.simple_server import make_server
from portal import auth, bootstrap, db
from portal.app import create_app

class LiveHTTP(unittest.TestCase):
    def test_http_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=str(Path(tmp)/"live.sqlite")
            conn=db.connect(path)
            auth.set_password(conn,"owner","fixture-password-long")
            conn.close()
            secret=Path(tmp)/"hook-file"
            secret.write_text("fixture-webhook-key")
            app=create_app(path,ops_enabled=True,reports_enabled=True,webhook_enabled=True,backup_dir=tmp,secure_cookie=False,
                           webhook_secret_file=str(secret),github_api=lambda *a:({"check_runs":[{"status":"completed","conclusion":"success"}],"total_count":1},None))
            server=make_server("127.0.0.1",0,app)
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            base="http://127.0.0.1:"+str(server.server_port)
            csrf=""
            def request(method,route,payload=None):
                raw=json.dumps(payload).encode() if payload is not None else None
                headers={"Content-Type":"application/json"}
                if csrf:headers["X-CSRF-Token"]=csrf
                req=urllib.request.Request(base+route,data=raw,headers=headers,method=method)
                with opener.open(req,timeout=5) as response:
                    body=response.read()
                    return json.loads(body) if response.headers.get("Content-Type","").startswith("application/json") else body
            try:
                csrf=request("POST","/api/login",{"username":"owner","password":"fixture-password-long"})["csrf"]
                request("POST","/api/projects",{"slug":"live-project","name":"Live"})
                request("POST","/api/projects/live-project/plan",{"plan":bootstrap.STARTER_PLAN})
                request("POST","/api/projects/live-project/status",{"id":"A1","status":"issued"})
                request("POST","/api/projects/live-project/status",{"id":"A1","status":"submitted"})
                request("POST","/api/projects/live-project/tasks/A1/report",{"text":"Finished"})
                request("POST","/api/projects/live-project/tasks/A1/review",{"return":True,"remarks":"Fix"})
                request("POST","/api/projects/live-project/status",{"id":"A1","status":"submitted"})
                request("POST","/api/projects/live-project/tasks/A1/review",{"items":[{"text":"Checked","checked":True}],"ci_state":"success"})
                request("POST","/api/projects/live-project/status",{"id":"A1","status":"accepted"})
                # A signed GitHub webhook is accepted by the actual HTTP server.
                payload={"repository":{"full_name":"owner/repo"},"ref":"refs/heads/feature"}
                raw=json.dumps(payload).encode()
                signature="sha256="+hmac.new(secret.read_bytes(),raw,hashlib.sha256).hexdigest()
                hook=urllib.request.Request(base+"/hook/github",data=raw,method="POST",
                     headers={"X-Hub-Signature-256":signature,"X-GitHub-Delivery":"a5-e2e-delivery-0001","X-GitHub-Event":"push","Content-Type":"application/json"})
                with opener.open(hook,timeout=5) as response:
                    self.assertEqual(response.status,200)
                request("POST","/api/backup",{})
                self.assertTrue(request("GET","/api/backup/latest").startswith(b"SQLite format 3"))
                data=request("GET","/api/projects/live-project/export")
                self.assertEqual(request("POST","/api/projects/import",{"data":data,"slug":"import-project"})["slug"],"import-project")
                self.assertEqual(request("DELETE","/api/projects/import-project",{"confirm":"import-project"})["deleted"],"import-project")
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()
                app.close()
