"""Thin Python WSGI entrypoint: modules own all routes and tables."""
import json
import os
from http import HTTPStatus
from wsgiref.simple_server import make_server
from server import db
from server.registry import Registry
from server import platform, ledger, clock, world, catalog
from server.platform.settings import read_settings


def build_registry():
    registry = Registry()
    for module in (platform, ledger, clock, world, catalog):
        registry.add(module)
    return registry


def create_app(dsn=None):
    registry = build_registry()
    with db.connect(dsn) as conn:
        db.migrate(conn, registry.modules)
        conn.commit()

    def app(environ, start_response):
        method = environ.get('REQUEST_METHOD', 'GET').upper()
        path = environ.get('PATH_INFO', '/')
        if path == '/' and method == 'GET':
            path = '/health'
        try:
            length = int(environ.get('CONTENT_LENGTH') or '0')
            if length > 65536 or length < 0:
                raise ValueError('payload too large')
            data = json.loads(environ['wsgi.input'].read(length) or b'{}')
            if not isinstance(data, dict):
                raise ValueError('expected JSON object')
            with db.connect(dsn) as conn:
                context = {'conn': conn, 'authorization': environ.get('HTTP_AUTHORIZATION',''), 'settings': read_settings(conn, registry.flags)}
                status, payload = registry.dispatch(method, path, data, context)
                conn.commit()
        except (ValueError, json.JSONDecodeError):
            status, payload = 400, {'error': 'invalid_request'}
        except Exception:
            status, payload = 503, {'error': 'service_unavailable'}
        encoded = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        start_response(f'{status} {HTTPStatus(status).phrase}', [('Content-Type', 'application/json; charset=utf-8'), ('Content-Length', str(len(encoded))), ('Cache-Control', 'no-store')])
        return [encoded]
    return app


def main():
    app = create_app()
    port = int(os.environ.get('LUNEX_PORT','18777'))
    with make_server('127.0.0.1', port, app) as service:
        print(f'LunexEconom V2 on localhost:{port}', flush=True)
        service.serve_forever()

if __name__ == '__main__': main()
