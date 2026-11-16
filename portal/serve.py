"""Запуск портала: python -m portal.serve. Слушает только 127.0.0.1 (наружу через nginx)."""
import os
import re
import sys
import threading
import time
from .backup.worker import tick
from .launch.plan_poll import poll_plans
from .launch.a7 import merge_due
from . import db
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from .app import create_app


class Threaded(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class Quiet(WSGIRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), re.sub(r"(/ctx/)[A-Za-z0-9_-]{22,64}",lambda match: match.group(1)+"[скрыто]",fmt % args)))


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
                     launch_enabled=enabled("launch","PORTAL_LAUNCH_ENABLED"),
                     review_a7_enabled=enabled("review_a7","PORTAL_REVIEW_A7_ENABLED"),
                     github_merge_token_file=os.environ.get("PORTAL_GITHUB_MERGE_TOKEN_FILE"),
                     memory_enabled=os.environ.get("PORTAL_MEMORY","1")=="1",
                     memory_root=os.environ.get("PORTAL_REPO_ROOT"))
    stop=threading.Event()
    def worker():
        while not stop.is_set():
            try:
                tick(path,tokens,os.environ.get("PORTAL_GITHUB_TOKEN_FILE"),
                     notifications=enabled("notifications","PORTAL_NOTIFICATIONS_ENABLED"),
                     webhook=enabled("webhook","PORTAL_WEBHOOK_ENABLED"))
                if enabled("launch","PORTAL_LAUNCH_ENABLED") and enabled("webhook","PORTAL_WEBHOOK_ENABLED"):
                    plan_conn = db.connect(path, webhook=True, reports=True, notifications=True)
                    try:
                        poll_plans(plan_conn, os.environ.get("PORTAL_GITHUB_TOKEN_FILE"),
                                   memory_enabled=os.environ.get("PORTAL_MEMORY","1")=="1",
                                   memory_root=os.environ.get("PORTAL_REPO_ROOT"))
                        if enabled("review_a7","PORTAL_REVIEW_A7_ENABLED"):
                            before=plan_conn.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]
                            merge_due(plan_conn,os.environ.get("PORTAL_GITHUB_MERGE_TOKEN_FILE"),os.environ.get("PORTAL_GITHUB_TOKEN_FILE"))
                            if enabled("notifications","PORTAL_NOTIFICATIONS_ENABLED"):
                                from . import notify
                                for ev in plan_conn.execute("SELECT project_slug,pkg_id,kind FROM events WHERE id>? AND kind IN ('task.auto_merge','task.ready')",(before,)):
                                    label='слита автоматически' if ev['kind']=='task.auto_merge' else 'готова к выдаче'
                                    notify.enqueue(plan_conn,'task.accepted',f"{ev['project_slug']}:{ev['pkg_id']}:{ev['kind']}",f"{ev['project_slug']}: задача {ev['pkg_id']} {label}. https://rikagro.ru/createportal/")
                    finally:
                        plan_conn.close()
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
