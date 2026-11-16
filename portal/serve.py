"""Запуск портала: python -m portal.serve. Слушает только 127.0.0.1 (наружу через nginx)."""
import os
import sys
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from .app import create_app


class Threaded(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class Quiet(WSGIRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


def main():
    path = os.environ.get("PORTAL_DB", "/var/lib/createportal/portal.sqlite")
    base = os.environ.get("PORTAL_BASE", "/createportal")
    port = int(os.environ.get("PORTAL_PORT", "18790"))
    secure = os.environ.get("PORTAL_INSECURE_COOKIE") != "1"
    app = create_app(path, base=base, secure_cookie=secure, github_token_file=os.environ.get("PORTAL_GITHUB_TOKEN_FILE"))
    with make_server("127.0.0.1", port, app, server_class=Threaded, handler_class=Quiet) as srv:
        srv.serve_forever()


if __name__ == "__main__":
    main()
