"""Threaded Waitress WSGI entrypoint, PostgreSQL pool, background clock worker."""
import json
import logging
import os
import threading
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs

from psycopg_pool import ConnectionPool
from waitress import serve
from server import db
from server.registry import Registry
from server import platform, ledger, clock, world, catalog
from server.platform.settings import read_settings
from server.platform.admin import authorized

LOGGER=logging.getLogger(__name__)
MAX_BODY=65536


def build_registry():
    registry=Registry()
    for module in (platform,ledger,clock,world,catalog):
        registry.add(module)
    return registry


def create_app(dsn=None, start_tick=False):
    registry=build_registry()
    url=dsn or os.environ.get('LUNEX_DATABASE_URL')
    if not url or not url.startswith(('postgresql://','postgres://')):
        raise RuntimeError('LUNEX_DATABASE_URL must be PostgreSQL')
    with db.connect(url) as connection:
        db.migrate(connection,registry.modules)
        clock.core.ensure_epoch(connection)
        connection.commit()
    pool=ConnectionPool(conninfo=url,min_size=int(os.getenv('LUNEX_POOL_MIN','2')),max_size=int(os.getenv('LUNEX_POOL_MAX','20')),timeout=10, max_waiting=200,kwargs={'options':'-c statement_timeout=7000 -c lock_timeout=5000 -c idle_in_transaction_session_timeout=10000'},open=True)
    pool.wait(timeout=15)
    stop=threading.Event()

    def app(environ,start_response):
        method=environ.get('REQUEST_METHOD','GET').upper()
        path=environ.get('PATH_INFO','/')
        if path=='/' and method=='GET': path='/health'
        if path=='/operator-ui' and method=='GET':
            host=environ.get('HTTP_HOST','').lower().rsplit(':',1)[0]
            if environ.get('REMOTE_ADDR') not in ('127.0.0.1','::1') or host not in ('127.0.0.1','localhost','[::1]') or environ.get('HTTP_X_FORWARDED_FOR') or environ.get('HTTP_FORWARDED'):
                return _send(start_response,403,{'error':'forbidden'})
            html=(Path(__file__).resolve().parent/'platform'/'admin_ui.html').read_bytes()
            start_response('200 OK',[('Content-Type','text/html; charset=utf-8'),('Content-Length',str(len(html))),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff')])
            return [html]
        admin_path=path.startswith('/admin/')
        if admin_path:
            ctx_guard={'remote_addr':environ.get('REMOTE_ADDR',''),'admin_token':environ.get('HTTP_X_ADMIN_TOKEN','')}
            host=environ.get('HTTP_HOST','').lower().rsplit(':',1)[0]
            if (not authorized(ctx_guard) or host not in ('localhost','127.0.0.1','[::1]') or environ.get('HTTP_X_FORWARDED_FOR') or environ.get('HTTP_FORWARDED') or environ.get('HTTP_X_REAL_IP')):
                return _send(start_response,403,{'error':'forbidden'})
        try:
            raw_length=environ.get('CONTENT_LENGTH','')
            length=int(raw_length or '0')
            if length<0 or length>MAX_BODY:
                return _send(start_response,413,{'error':'request_too_large'})
            if method in ('POST','PUT','PATCH') and not raw_length:
                return _send(start_response,411,{'error':'length_required'})
            data=json.loads(environ['wsgi.input'].read(length) or b'{}')
            if not isinstance(data,dict):
                return _send(start_response,400,{'error':'expected_json_object'})
            with pool.connection() as conn:
                with conn.transaction():
                    context={'conn':conn,'pool':pool,'registry':registry,'authorization':environ.get('HTTP_AUTHORIZATION',''),'remote_addr':environ.get('REMOTE_ADDR','127.0.0.1'),'real_ip':environ.get('HTTP_X_REAL_IP',''),'admin_token':environ.get('HTTP_X_ADMIN_TOKEN',''),'query':parse_qs(environ.get('QUERY_STRING','')),'client_version':environ.get('HTTP_X_CLIENT_VERSION',''),'if_none_match':environ.get('HTTP_IF_NONE_MATCH','')}
                    context['settings']=read_settings(conn,registry.flags,registry.flag_constraints)
                    status,payload=registry.dispatch(method,path,data,context)
        except (ValueError,UnicodeError,json.JSONDecodeError):
            return _send(start_response,400,{'error':'invalid_request'})
        except Exception:
            LOGGER.exception('Platform request failure %s %s',method,path)
            return _send(start_response,503,{'error':'service_unavailable'})
        if path == '/catalog' and method == 'GET' and status in (200,304):
            return _send_catalog(start_response,status,payload,registry.catalog.etag)
        return _send(start_response,status,payload)

    def tick_loop():
        while not stop.is_set():
            try:
                with pool.connection() as conn:
                    state=clock.core.run_pending(conn,registry,limit=5)
                    if state['pending']>5:
                        LOGGER.info('Tick backlog remaining %s days',state['pending'])
            except Exception:
                LOGGER.exception('Background tick failed, will retry')
            stop.wait(float(os.getenv('LUNEX_TICK_INTERVAL','5')))

    app.pool=pool
    app.registry=registry
    app.stop_tick=stop.set
    app.close=lambda: (stop.set(),pool.close())
    if start_tick:
        threading.Thread(target=tick_loop,daemon=True,name='lunex-game-clock').start()
    return app



def _send_catalog(start_response, status, payload, etag):
    encoded = b'' if status == 304 else json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    start_response(f'{status} {HTTPStatus(status).phrase}', [
        ('Content-Type','application/json; charset=utf-8'),
        ('Content-Length',str(len(encoded))),
        ('Cache-Control','public, max-age=0, must-revalidate'),
        ('ETag',etag),
        ('X-Content-Type-Options','nosniff'),
    ])
    return [encoded]


def _send(start_response,status,payload):
    encoded=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    start_response(f'{status} {HTTPStatus(status).phrase}', [('Content-Type','application/json; charset=utf-8'),('Content-Length',str(len(encoded))),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff')])
    return [encoded]


def main():
    logging.basicConfig(level=os.getenv('LUNEX_LOG_LEVEL','INFO'))
    app=create_app(start_tick=True)
    port=int(os.environ.get('LUNEX_PORT','18777'))
    print(f'LunexEconom V2.1 on 127.0.0.1:{port}',flush=True)
    try:
        serve(app,host='127.0.0.1',port=port,threads=int(os.getenv('LUNEX_THREADS','32')),connection_limit=300, channel_timeout=20, max_request_body_size=MAX_BODY)
    finally:
        app.close()

if __name__=='__main__': main()
