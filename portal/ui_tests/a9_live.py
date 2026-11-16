"""Сквозная HTTP-проверка A9 на локальном тестовом WSGI-сервере."""
import io
import json
import tempfile
import threading
import urllib.request
from pathlib import Path
from wsgiref.simple_server import make_server
from portal import db,auth
from portal.app import create_app

with tempfile.TemporaryDirectory() as d:
    path=str(Path(d)/'live.sqlite')
    conn=db.connect(path,webhook=True,reports=True,notifications=True)
    conn.execute("INSERT INTO projects(slug,name,repo,description,plan_json,created) VALUES('demo-project','Demo','owner/repo','safe','{\"packages\":[]}',1)")
    conn.close()
    app=create_app(path,webhook_enabled=True,reports_enabled=True,notifications_enabled=True,ops_enabled=True,memory_root=str(Path(__file__).resolve().parents[2]))
    server=make_server('127.0.0.1',0,app)
    worker=threading.Thread(target=server.serve_forever,daemon=True)
    worker.start()
    url='http://127.0.0.1:%s'%server.server_port
    try:
        with urllib.request.urlopen(url+'/api/projects/demo-project/context') as response:
            assert response.status==401
        raise AssertionError('authorization bypass')
    except urllib.error.HTTPError as e:
        assert e.code==401
    finally:
        server.shutdown();server.server_close();app.close()
print('A9 live HTTP: unauthorized context denied, PASS')
