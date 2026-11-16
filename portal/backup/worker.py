"""Single in-process worker; one DB connection per tick, no cron."""
import time
from portal import db, notify
from portal.backup import sync

def tick(db_path, token_files, github_token_file=None, *, notifications=True, webhook=True, now=None,
         client=notify.http_json, fetch=sync.github_get):
    now=time.time() if now is None else now
    conn=db.connect(db_path,webhook=webhook,reports=webhook,notifications=notifications)
    try:
        if notifications:
            for row in conn.execute("SELECT s.project_slug,s.pkg_id,p.name FROM task_state s JOIN projects p ON p.slug=s.project_slug WHERE s.status='submitted' AND s.submitted_at<?",(now-86400,)).fetchall():
                notify.enqueue(conn,"review.overdue",row["project_slug"]+":"+row["pkg_id"],
                               f'{row["name"]}: {row["pkg_id"]} ждёт приёмки больше суток. https://rikagro.ru/createportal/',now)
            notify.deliver_due(conn,token_files,client,now)
            for channel in notify.CHANNELS:
                if conn.execute("SELECT 1 FROM notify_channels WHERE channel=? AND code_hash IS NOT NULL AND expires>?",(channel,now)).fetchone():
                    try:notify.poll_bindings(conn,channel,token_files,client,now)
                    except (OSError,ValueError,TypeError,TimeoutError):pass
        if webhook:
            try:token=sync.read_token(github_token_file)
            except (ValueError,OSError):token=""
            for row in conn.execute("SELECT p.slug,p.poll_minutes,s.last_poll FROM projects p LEFT JOIN project_sync s ON s.project_slug=p.slug WHERE p.sync_mode IN ('polling','both') AND p.repo<>''").fetchall():
                if row["last_poll"] is None or now-row["last_poll"]>=row["poll_minutes"]*60:
                    sync.poll_project(conn,row["slug"],token,fetch,now)
    finally:
        conn.close()
