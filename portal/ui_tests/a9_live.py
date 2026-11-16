"""A9: isolated real HTTP WSGI server, session, CSRF, temporary link, revoke."""
import io
import json
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from wsgiref.simple_server import make_server
from portal import auth,db
from portal.app import create_app
from portal.ui_tests.shots import Quiet

with tempfile.TemporaryDirectory(prefix='portal-a9-live-') as directory:
    database=str(Path(directory)/'live.sqlite')
    conn=db.connect(database,webhook=True,reports=True,notifications=True)
    auth.set_password(conn,'fixture','fixture-local-only-password')
    conn.execute("INSERT INTO projects(slug,name,repo,description,plan_json,created) VALUES(?,?,?,?,?,?)",
                 ('demo-project','Demo','owner/project','safe','{"packages":[]}',1))
    conn.close()
    def github_stub(url,token='',etag=None):
        if '/git/trees/' in url:
            return {'tree':[],'truncated':False},None
        raise ValueError('fixture_missing')
    app=create_app(database,base='/createportal',secure_cookie=False,webhook_enabled=True,
                   reports_enabled=True,notifications_enabled=True,ops_enabled=True,github_api=github_stub)
    server=make_server('127.0.0.1',0,app,handler_class=Quiet)
    worker=threading.Thread(target=server.serve_forever,daemon=True)
    worker.start()
    endpoint='http://127.0.0.1:%s/createportal'%server.server_port
    def request(method,path,data=None,cookie='',csrf=''):
        payload=json.dumps(data).encode() if data is not None else None
        req=urllib.request.Request(endpoint+path,data=payload,method=method,headers={
            'Content-Type':'application/json','Cookie':cookie,'X-CSRF-Token':csrf})
        try:
            with urllib.request.urlopen(req,timeout=10) as response:
                raw=response.read()
                return response.status,dict(response.headers),json.loads(raw) if response.headers.get_content_type()=='application/json' else raw.decode()
        except urllib.error.HTTPError as exc:
            return exc.code,dict(exc.headers),exc.read().decode()
    try:
        assert request('GET','/api/projects/demo-project/context')[0]==401
        login=request('POST','/api/login',{'username':'fixture','password':'fixture-local-only-password'})
        assert login[0]==200
        cookie=login[1]['Set-Cookie'].split(';')[0]
        csrf=login[2]['csrf']
        assert request('POST','/api/projects/demo-project/context-link',{},cookie)[0]==403
        code,headers,body=request('GET','/api/projects/demo-project/context',cookie=cookie)
        assert code==200 and body['text'].startswith('# Контекст') and len(body['text'])<=6000
        created=request('POST','/api/projects/demo-project/context-link',{},cookie,csrf)
        assert created[0]==200
        token=created[2]['token']
        public=request('GET',created[2]['url'].removeprefix('/createportal'))
        assert public[0]==200 and public[1].get('Content-Type','').startswith('text/plain')
        assert 'Demo' in public[2]
        assert request('POST','/api/projects/demo-project/context-link',{'revoke':token},cookie,csrf)[0]==200
        assert request('GET',created[2]['url'].removeprefix('/createportal'))[0]==404
        added=request('POST','/api/projects/demo-project/decisions',
                      {'title':'Test decision','text':'Approved via HTTP'},cookie,csrf)
        assert added[0]==200
        assert any('Approved via HTTP' in v['text'] for v in request('GET','/api/projects/demo-project/decisions',cookie=cookie)[2]['decisions'])
        print('A9 real HTTP WSGI E2E OK: login, CSRF, context, public link, revoke, decisions')
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
        app.close()
