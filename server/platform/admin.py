"""Loopback-only, explicit secret-token protected operator API."""
import hmac
import json
import os
import time
from . import settings
from psycopg.types.json import Jsonb
from .api import STARTED


def authorized(ctx):
    addr=ctx.get('remote_addr','')
    if addr not in ('127.0.0.1','::1'):
        return False
    configured=os.getenv('LUNEX_ADMIN_TOKEN','')
    presented=ctx.get('admin_token','')
    return bool(configured) and len(configured)>=24 and isinstance(presented,str) and hmac.compare_digest(configured,presented)


def overview(body,ctx):
    conn=ctx['conn']
    health=conn.execute('SELECT 1').fetchone()==(1,)
    last=conn.execute('SELECT day_index,duration_ms,error,finished_at FROM game_ticks ORDER BY day_index DESC LIMIT 1').fetchone()
    people=conn.execute('SELECT count(*) FROM accounts').fetchone()[0]
    online=conn.execute("SELECT count(*) FROM presence WHERE seen_at>=now()-interval '90 seconds'").fetchone()[0]
    peak=conn.execute("SELECT COALESCE(max(peak),0) FROM presence_daily_peak WHERE day=(now() AT TIME ZONE 'Asia/Yekaterinburg')::date").fetchone()[0]
    errors=conn.execute("SELECT count(*) FROM game_ticks WHERE error IS NOT NULL AND started_at>=now()-interval '1 day'").fetchone()[0]
    return 200,{'version':os.getenv('LUNEX_VERSION','v2.1.0-dev'),'sha':os.getenv('LUNEX_SHA','unknown'),'uptime_seconds':int(time.monotonic()-STARTED),'database':'ok' if health else 'down','pool':ctx['pool'].get_stats() if ctx.get('pool') else {},'last_tick':{'day':last[0],'duration_ms':last[1],'error':last[2],'at':last[3].isoformat() if last[3] else None} if last else None,'online':online,'peak_24h':peak,'players':people,'errors_24h':errors}


def flags(body,ctx):
    current=settings.read_settings(ctx['conn'],ctx['registry'].flags,ctx['registry'].flag_constraints)
    return 200,{'flags':current,'defaults':ctx['registry'].flags,'bounds':ctx['registry'].flag_constraints}


def get_settings(body,ctx):
    return flags(body,ctx)


def update_settings(body,ctx):
    try:
        result=settings.change(ctx['conn'],body.get('key'),body.get('value'),body.get('apply_at','now'),'admin:loopback',ctx['registry'].flags,ctx['registry'].flag_constraints)
    except ValueError as exc:
        return 400,{'error':str(exc)}
    return 200,result


def revisions(body,ctx):
    rows=ctx['conn'].execute('SELECT revision,key,new_value,apply_at,effective_month,actor,created_at FROM runtime_revisions ORDER BY revision DESC LIMIT 100').fetchall()
    return 200,{'items':[{'revision':r[0],'key':r[1],'value':r[2],'apply_at':r[3],'effective_month':r[4],'actor':r[5],'at':r[6].isoformat()} for r in rows]}


def undo(body,ctx):
    try:
        result=settings.rollback(ctx['conn'],int(body.get('revision')),'admin:loopback',ctx['registry'].flags,ctx['registry'].flag_constraints)
    except (TypeError,ValueError) as exc:
        return 400,{'error':str(exc)}
    return 200,result


def audit(body,ctx):
    rows=ctx['conn'].execute('SELECT id,actor,action,payload,created_at FROM audit ORDER BY id DESC LIMIT 100').fetchall()
    return 200,{'items':[{'id':r[0],'actor':r[1],'action':r[2],'payload':r[3],'at':r[4].isoformat()} for r in rows]}


def block(body,ctx):
    username=body.get('username')
    blocked=body.get('blocked')
    if not isinstance(username,str) or type(blocked) is not bool:
        return 400,{'error':'invalid_request'}
    with ctx['conn'].transaction():
        row=ctx['conn'].execute('UPDATE accounts SET is_blocked=%s WHERE lower(username)=lower(%s) RETURNING id',(blocked,username)).fetchone()
        if row is None:
            return 404,{'error':'not_found'}
        if blocked:
            ctx['conn'].execute('UPDATE sessions SET revoked_at=now() WHERE account_id=%s',(row[0],))
        ctx['conn'].execute('INSERT INTO audit(actor,action,payload) VALUES(%s,%s,%s)',('admin:loopback','account.block',Jsonb({'username':username,'blocked':blocked})))
    return 200,{'ok':True}
