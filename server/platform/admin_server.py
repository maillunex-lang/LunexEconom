"""A2 safe admin diagnostics, input limits and computed alerts."""
import hashlib
import re
import time
from pathlib import Path

from server.platform import admin
from server.platform.api import health
from server.ledger.api import reconcile


def integer(value, low=0, high=100):
    if isinstance(value,bool) or not re.fullmatch(r'(0|[1-9][0-9]{0,18})',str(value)):
        raise ValueError('invalid_integer')
    parsed = int(value)
    if not low<=parsed<=high:
        raise ValueError('out_of_range')
    return parsed


def page(ctx, maximum=100, default=50):
    limit=integer(admin._query(ctx,'limit',str(default)),1,maximum)
    after=integer(admin._query(ctx,'after','0'),0,2**63-1)
    return limit,after


def guard(ctx, roles=admin.READ):
    actor,err=admin._need(ctx,roles)
    if err:return None,err
    # Transaction-local timeout applies to the current admin request (not every game request).
    ctx['conn'].execute("SELECT set_config('statement_timeout','5000',true)")
    return actor,None


def _latest(ctx, query, values=(), limit=50):
    return ctx['conn'].execute(query,(*values,limit)).fetchall()


def _redact_error(value):
    # Never return arbitrary exception messages or request bodies to the browser.
    if value is None:return None
    return 'Ошибка игрового обработчика (подробности доступны в защищённом журнале сервера)'


def ticks(body,ctx):
    actor,err=guard(ctx)
    if err:return err
    try:limit,after=page(ctx)
    except ValueError:return 400,{'error':'invalid_pagination'}
    rows=_latest(ctx,'''SELECT day_index,started_at,finished_at,duration_ms,completed,error
                     FROM game_ticks WHERE day_index<%s ORDER BY day_index DESC LIMIT %s''',
                 (after if after else 2**63-1,),limit)
    items=[{'day':int(r[0]),'started_at':r[1].isoformat(),
            'finished_at':r[2].isoformat() if r[2] else None,
            'duration_ms':int(r[3]) if r[3] is not None else None,
            'completed':r[4],'error':_redact_error(r[5])} for r in rows]
    return 200,{'items':items,'limit':limit,'next_after':items[-1]['day'] if len(items)==limit else None}


def errors(body,ctx):
    actor,err=guard(ctx)
    if err:return err
    try:limit,after=page(ctx)
    except ValueError:return 400,{'error':'invalid_pagination'}
    record_tick_errors(ctx['conn'])
    rows=_latest(ctx,'''SELECT id,origin,day_index,error_code,created_at FROM admin_error_log
                       WHERE id<%s ORDER BY id DESC LIMIT %s''', (after if after else 2**63-1,),limit)
    items=[{'id':r[0],'origin':r[1],'day_index':r[2],'error_code':r[3],
            'at':r[4].isoformat()} for r in rows]
    return 200,{'items':items,'limit':limit,'next_after':items[-1]['id'] if len(items)==limit else None}


def _migrations(conn):
    base=Path(__file__).resolve().parents[1]/'migrations'
    rows=conn.execute('SELECT name,sha256 FROM schema_migrations ORDER BY name').fetchall()
    mismatches=[]
    for name,recorded in rows:
        if not re.fullmatch(r'[0-9]{12}_[a-zA-Z0-9_]+\.sql',name):
            mismatches.append(name)
            continue
        path=base/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=recorded:
            mismatches.append(name)
    return {'count':len(rows),'sha256_ok':not mismatches,'mismatches':mismatches}


def server(body,ctx):
    actor,err=guard(ctx)
    if err:return err
    conn=ctx['conn']
    code,status=health({},ctx)
    status.pop('tick',None)
    status['uptime_seconds']=int(time.monotonic()-admin.STARTED)
    status['database_size_bytes']=int(conn.execute('SELECT pg_database_size(current_database())').fetchone()[0])
    status['admin_sessions_active']=int(conn.execute('''SELECT count(*) FROM admin_sessions
          WHERE revoked_at IS NULL AND expires_at>now() AND absolute_expires_at>now()''').fetchone()[0])
    status['migrations']=_migrations(conn)
    status['ticks']=ticks({},dict(ctx,query={'limit':['50']}))[1]['items']
    return 200,status


def alerts(body,ctx):
    actor,err=guard(ctx)
    if err:return err
    conn=ctx['conn']; items=[]
    def alert(code,level,description,link):
        items.append({'code':code,'level':level,'text':description,'link':link})
    row=conn.execute('SELECT day_index,duration_ms,error,completed FROM game_ticks ORDER BY day_index DESC LIMIT 1').fetchone()
    if row and (row[2] or not row[3]): alert('tick_failed','crit','Последний игровой тик завершился ошибкой','/ticks')
    if row and row[1] is not None and row[1]>30000: alert('tick_slow','warn','Игровой тик выполнялся дольше 30 секунд','/ticks')
    if not reconcile(conn)['ok']: alert('ledger_mismatch','crit','Сверка денежных проводок выявила расхождения','/economy')
    if conn.execute("SELECT 1 FROM ledger_accounts WHERE kind='player' AND balance<0 LIMIT 1").fetchone():
        alert('negative_balance','crit','Обнаружен отрицательный баланс игрока','/economy')
    if conn.execute("SELECT count(*) FROM accounts WHERE created_at>=now()-interval '1 hour'").fetchone()[0]>50:
        alert('registration_spike','warn','Более 50 регистраций за последний час','/overview')
    if conn.execute('''SELECT 1 FROM enterprise_build_waits WHERE waiting_days>5 LIMIT 1''').fetchone() or conn.execute(
          '''SELECT 1 FROM enterprise_arrears WHERE paid_at IS NULL AND consecutive_months>0
             AND month_index*30 < (SELECT COALESCE(MAX(day_index),-1)-5 FROM game_ticks WHERE completed) LIMIT 1''').fetchone():
        alert('enterprise_overdue','warn','Предприятие простаивает из-за просрочки более пяти игровых суток','/economy')
    if conn.execute('SELECT 1 FROM world_cities WHERE growth_enabled=false LIMIT 1').fetchone():
        alert('city_growth_disabled','info','Рост одного или нескольких городов отключён','/cities')
    return 200,{'items':items,'count':len(items)}


def record_tick_errors(conn, day=None):
    """Idempotently collect committed failed ticks. Can run in a normal daily hook or admin request."""
    conn.execute('''INSERT INTO admin_error_log(origin,day_index,error_code)
      SELECT 'tick',t.day_index,'tick_failed' FROM game_ticks t WHERE t.error IS NOT NULL
      ON CONFLICT (origin,day_index) DO NOTHING''')
    conn.execute('''DELETE FROM admin_error_log WHERE id IN
        (SELECT id FROM admin_error_log ORDER BY id DESC OFFSET 1000)''')
