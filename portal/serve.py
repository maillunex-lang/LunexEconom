"""Запуск портала: python -m portal.serve. Слушает только 127.0.0.1 (наружу через nginx)."""
import os
import sys
import threading
import time
from .backup.worker import tick
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
    features={x.strip() for x in os.environ.get("PORTAL_FEATURES","webhook,reports,notifications,ops").split(",")}
    def enabled(name,env):
        return os.environ.get(env,"1" if name in features else "0")=="1"
    tokens={"max":os.environ.get("PORTAL_MAX_TOKEN_FILE"),"telegram":os.environ.get("PORTAL_TELEGRAM_TOKEN_FILE")}
    app = create_app(path, base=base, secure_cookie=secure, github_token_file=os.environ.get("PORTAL_GITHUB_TOKEN_FILE"),
                     security_v2=os.environ.get("PORTAL_SECURITY_V2", "1") != "0",
                     webhook_enabled=enabled("webhook","PORTAL_WEBHOOK_ENABLED"),
                     webhook_secret_file=os.environ.get("PORTAL_WEBHOOK_SECRET_FILE"),
                     reports_enabled=enabled("reports","PORTAL_REPORTS_ENABLED"),
                     notifications_enabled=enabled("notifications","PORTAL_NOTIFICATIONS_ENABLED"),
                     notify_token_files=tokens,ops_enabled=enabled("ops","PORTAL_OPS_ENABLED"),backup_dir=os.environ.get("PORTAL_BACKUP_DIR"),
                     launch_enabled=enabled("launch","PORTAL_LAUNCH_ENABLED"))
    stop=threading.Event()
    def worker():
        while not stop.is_set():
            try:
                tick(path,tokens,os.environ.get("PORTAL_GITHUB_TOKEN_FILE"),
                     notifications=enabled("notifications","PORTAL_NOTIFICATIONS_ENABLED"),
                     webhook=enabled("webhook","PORTAL_WEBHOOK_ENABLED"))
            except Exception:
                # Do not log exception bodies: HTTP libraries may include token URLs.
                sys.stderr.write("CreatePortal: background tick failed\n")
            stop.wait(60)
    background=threading.Thread(target=worker,name="portal-worker",daemon=True)
    background.start()
    with make_server("127.0.0.1", port, app, server_class=Threaded, handler_class=Quiet) as srv:
        try:
            srv.serve_forever()
        finally:
            stop.set()
            background.join(timeout=5)
            app.close()


if __name__ == "__main__":
    main()
