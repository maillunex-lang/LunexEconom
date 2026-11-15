"""Typed live configuration: code defaults < environment < eligible DB revisions."""
import json
import os
from server.clock.core import clock_view
from psycopg.types.json import Jsonb

BOUNDS = {'registration_enabled':None,'clock_enabled':None,'ledger_enabled':None,'world_enabled':None}


def validate(name,value,defaults,bounds=None):
    if name not in defaults or type(value) is not type(defaults[name]):
        raise ValueError('unknown setting or invalid type')
    spec=(bounds or {}).get(name)
    if spec and isinstance(value,(int,float)) and not isinstance(value,bool):
        low,high=spec
        if low is not None and value<low or high is not None and value>high:
            raise ValueError('out of range')
    return value


def current_month(conn):
    row=conn.execute('SELECT epoch FROM platform_clock WHERE id=1').fetchone()
    return clock_view(row[0])['month_index'] if row else 0


def read_settings(conn,defaults,bounds=None):
    result=dict(defaults)
    for key in defaults:
        env=os.getenv('LUNEX_FLAG_'+key.upper())
        if env is not None:
            try:
                result[key]=validate(key,json.loads(env),defaults,bounds)
            except (ValueError,TypeError) as exc:
                raise ValueError('invalid environment flag '+key) from exc
    for key,value in conn.execute('SELECT key,value FROM runtime_config'):
        if key in defaults:
            result[key]=validate(key,value,defaults,bounds)
    month=current_month(conn)
    rows=conn.execute('SELECT key,new_value FROM runtime_revisions WHERE effective_month IS NULL OR effective_month<=%s ORDER BY revision',(month,)).fetchall()
    for key,value in rows:
        if key in defaults:
            result[key]=validate(key,value,defaults,bounds)
    return result


def change(conn,key,value,apply_at,actor,defaults,bounds=None):
    validate(key,value,defaults,bounds)
    if apply_at not in ('now','next_month'):
        raise ValueError('invalid apply_at')
    before=read_settings(conn,defaults,bounds).get(key)
    month=current_month(conn)
    effective=month+1 if apply_at=='next_month' else None
    with conn.transaction():
        revision=conn.execute('INSERT INTO runtime_revisions(key,old_value,new_value,apply_at,effective_month,actor) VALUES(%s,%s,%s,%s,%s,%s) RETURNING revision',(key,Jsonb(before),Jsonb(value),apply_at,effective,actor)).fetchone()[0]
        conn.execute('INSERT INTO audit(actor,action,payload) VALUES(%s,%s,%s)',(actor,'setting.change',json.dumps({'revision':revision,'key':key,'apply_at':apply_at})))
    return {'revision':revision,'key':key,'apply_at':apply_at,'effective_month':effective}


def rollback(conn,revision,actor,defaults,bounds=None):
    row=conn.execute('SELECT key,old_value FROM runtime_revisions WHERE revision=%s',(revision,)).fetchone()
    if row is None or row[1] is None:
        raise ValueError('revision not found')
    return change(conn,row[0],row[1],'now',actor,defaults,bounds)
