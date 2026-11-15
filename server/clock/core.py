"""ADR-001: one atomic transaction per game day, ordered hooks, bounded catchup."""
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Asia/Yekaterinburg')
MONTH_SECONDS = 86400
DAY_SECONDS = 2880
START_YEAR = 2027
LOGGER = logging.getLogger(__name__)
LOCK_ID = 2026111501


def align_epoch(now):
    local = now.astimezone(ZONE)
    anchor = local.replace(hour=9, minute=0, second=0, microsecond=0)
    if local < anchor:
        anchor -= timedelta(days=1)
    return anchor.astimezone(timezone.utc)


def next_epoch(now):
    return align_epoch(now) + timedelta(days=1)


def indices(epoch, now):
    elapsed = max(0, int((now-epoch).total_seconds()))
    return elapsed // DAY_SECONDS, elapsed // MONTH_SECONDS


def ensure_epoch(conn, now=None):
    """Create first epoch at the *next* 09:00 Ufa. Never change an existing world."""
    now = now or datetime.now(timezone.utc)
    epoch = next_epoch(now)
    conn.execute('INSERT INTO platform_clock(id,epoch) VALUES(1,%s) ON CONFLICT DO NOTHING', (epoch,))
    return conn.execute('SELECT epoch FROM platform_clock WHERE id=1').fetchone()[0]


def clock_view(epoch, now=None):
    now = now or datetime.now(timezone.utc)
    days,months=indices(epoch,now)
    current=epoch+timedelta(seconds=MONTH_SECONDS*(months+1)) if now>=epoch else epoch
    remaining=max(0,int((current-now).total_seconds()))
    return {'year':START_YEAR+months//12,'month':months%12+1,'month_index':months,'day':days%30+1,'day_index':days,'seconds_until_month':remaining,'next_boundary_ufa':current.astimezone(ZONE).isoformat(),'seconds_until_start':max(0,int((epoch-now).total_seconds()))}


def ordered_handlers(registry, kind):
    return sorted(registry.tick_handlers[kind],key=lambda entry:(entry[0],entry[1]))


def _failed(conn, day, started, handled, exc):
    # Day's work was rolled back already; diagnostic row commits separately.
    try:
        with conn.transaction():
            conn.execute("INSERT INTO game_ticks(day_index,started_at,finished_at,duration_ms,handlers,error,completed) VALUES(%s,%s,now(),%s,%s,%s,false) ON CONFLICT(day_index) DO UPDATE SET started_at=excluded.started_at,finished_at=excluded.finished_at,duration_ms=excluded.duration_ms,handlers=excluded.handlers,error=excluded.error,completed=false",(day,started,int((time.monotonic()-handled['started'])*1000),json.dumps(handled['names']),str(exc)[:500]))
    except Exception:
        LOGGER.exception('Unable to record failed tick %s',day)


def run_pending(conn,registry,epoch=None,now=None,limit=5):
    """Run at most `limit` missing days. Each day commits independently, even on failure."""
    if not 1<=limit<=100:
        raise ValueError('invalid catchup limit')
    now=now or datetime.now(timezone.utc)
    if epoch is None:
        with conn.transaction():
            epoch=ensure_epoch(conn,now)
    if now<epoch:
        return {'processed':0,'pending':0,'error':None}
    final,_=indices(epoch,now)
    processed=0
    failure=None
    for _ in range(limit):
        began=datetime.now(timezone.utc)
        handled={'names':[],'started':time.monotonic()}
        day=None
        try:
            with conn.transaction():
                if not conn.execute('SELECT pg_try_advisory_xact_lock(%s)',(LOCK_ID,)).fetchone()[0]:
                    break
                completed=conn.execute('SELECT COALESCE(MAX(day_index),-1) FROM game_ticks WHERE completed=true').fetchone()[0]
                day=completed+1
                if day>final:
                    break
                for order,name,handler in ordered_handlers(registry,'daily'):
                    handler(conn,day)
                    handled['names'].append('daily:'+name)
                if day%30==0:
                    for order,name,handler in ordered_handlers(registry,'monthly'):
                        handler(conn,day//30)
                        handled['names'].append('monthly:'+name)
                duration=int((time.monotonic()-handled['started'])*1000)
                conn.execute("INSERT INTO game_ticks(day_index,started_at,finished_at,duration_ms,handlers,error,completed) VALUES(%s,%s,now(),%s,%s,NULL,true) ON CONFLICT(day_index) DO UPDATE SET started_at=excluded.started_at,finished_at=excluded.finished_at,duration_ms=excluded.duration_ms,handlers=excluded.handlers,error=NULL,completed=true",(day,began,duration,json.dumps(handled['names'])))
                conn.execute("INSERT INTO tick_receipts(kind,tick_index) VALUES('daily',%s) ON CONFLICT DO NOTHING",(day,))
                if day%30==0:
                    conn.execute("INSERT INTO tick_receipts(kind,tick_index) VALUES('monthly',%s) ON CONFLICT DO NOTHING",(day//30,))
            processed+=1
            if duration>2000:
                LOGGER.warning('Game tick %s exceeded 2s: %sms',day,duration)
        except Exception as exc:
            failure=str(exc)[:500]
            LOGGER.exception('Day %s rolled back',day)
            if day is not None:
                _failed(conn,day,began,handled,exc)
            break
    last=conn.execute('SELECT COALESCE(MAX(day_index),-1) FROM game_ticks WHERE completed=true').fetchone()[0]
    return {'processed':processed,'pending':max(0,final-last),'error':failure}


def apply_ticks(conn,registry,epoch,now):
    """Backwards-compatible entrypoint: now uses bounded atomic daily runs."""
    return run_pending(conn,registry,epoch,now,limit=5)


def get_clock(body,ctx):
    epoch=ensure_epoch(ctx['conn'])
    state=clock_view(epoch)
    last=ctx['conn'].execute('SELECT day_index,duration_ms,error FROM game_ticks ORDER BY day_index DESC LIMIT 1').fetchone()
    state['tick']={'last_day':last[0],'last_duration_ms':last[1],'error':last[2]} if last else None
    return 200,state
