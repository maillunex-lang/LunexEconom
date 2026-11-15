"""Authenticated administration API with emergency loopback access."""
import hmac, json, os, time
from datetime import datetime, timezone
from . import settings
from .api import STARTED, _ip
from .security import hash_password, verify_password, new_token, token_hash
from psycopg.types.json import Jsonb
from server.ledger.api import account as ledger_account, transfer as ledger_transfer, reconcile

ROLES = ('owner','admin','support','viewer')
READ = {'owner','admin','support','viewer'}
WRITE_PLAYERS = {'owner','admin','support'}
WRITE_SETTINGS = {'owner','admin'}
ALL = {'owner'}


def _query(ctx, key, default=None):
    values = ctx.get('query',{}).get(key)
    return values[0] if values else default


def authorized(ctx):
    addr = ctx.get('remote_addr','')
    configured = os.getenv('LUNEX_ADMIN_TOKEN','')
    presented = ctx.get('admin_token','')
    host = str(ctx.get('host','')).lower().rsplit(':',1)[0]
    return (addr in ('127.0.0.1','::1') and host in ('localhost','127.0.0.1','[::1]')
            and not ctx.get('forwarded') and bool(configured) and len(configured)>=24
            and isinstance(presented,str) and hmac.compare_digest(configured,presented))


def _actor(ctx, minimum=READ):
    if authorized(ctx):
        return {'id':None,'username':'admin:loopback','role':'owner','emergency':True}
    auth = ctx.get('authorization','')
    if not isinstance(auth,str) or not auth.startswith('Bearer '):
        return None
    value = auth[7:]
    row = ctx['conn'].execute('''SELECT s.account_id,a.username,a.role,a.is_blocked,s.expires_at,s.absolute_expires_at
        FROM admin_sessions s JOIN accounts a ON a.id=s.account_id
        WHERE s.token_hash=%s AND s.revoked_at IS NULL
          AND s.expires_at>now() AND s.absolute_expires_at>now()
          AND (a.is_blocked=false OR (a.blocked_until IS NOT NULL AND a.blocked_until<=now()))''',(token_hash(value),)).fetchone()
    if not row or row[2] not in minimum:
        return None
    ctx['conn'].execute('UPDATE admin_sessions SET last_seen_at=now(), expires_at=LEAST(now()+interval \'60 minutes\', absolute_expires_at) WHERE token_hash=%s',(token_hash(value),))
    return {'id':row[0],'username':row[1],'role':row[2],'emergency':False}


def _need(ctx, roles):
    # Distinguish an unauthenticated request from an authenticated role without permission.
    actor = _actor(ctx, READ)
    if not actor:
        return None, (403, {'error':'forbidden'})
    if actor['role'] not in roles:
        return None, (403, {'error':'forbidden'})
    return actor, None


def _audit(ctx, actor, action, payload=None, target=None, old=None, new=None):
    payload = payload or {}
    ctx['conn'].execute('''INSERT INTO audit(actor,actor_role,target_account_id,action,payload,ip,old_value,new_value)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s)''', (actor['username'],actor['role'],target,action,Jsonb(payload),_ip(ctx),Jsonb(old) if old is not None else None,Jsonb(new) if new is not None else None))


def login(body,ctx):
    identifier,password=body.get('username') or body.get('email'),body.get('password')
    if not isinstance(identifier,str) or not isinstance(password,str): return 401,{'error':'invalid_credentials'}
    ip=_ip(ctx)
    if not _admin_attempt(ctx['conn'],identifier,ip): return 429,{'error':'rate_limited'}
    row=ctx['conn'].execute('SELECT id,username,password_hash,role,is_blocked,blocked_until FROM accounts WHERE lower(username)=lower(%s) OR email=%s',(identifier,identifier.lower())).fetchone()
    # Deliberately identical for unknown, blocked and wrong password.
    if not row or (row[4] and not (row[5] is not None and row[5] <= __import__('datetime').datetime.now(__import__('datetime').timezone.utc))) or row[3] not in ROLES or not verify_password(password,row[2]): return 401,{'error':'invalid_credentials'}
    if len(password)<14: return 400,{'error':'admin_password_too_short','message':'задайте пароль не короче 14 символов'}
    token=new_token()
    with ctx['conn'].transaction():
        ctx['conn'].execute('INSERT INTO admin_sessions(token_hash,account_id,ip,expires_at,absolute_expires_at) VALUES(%s,%s,%s,now()+interval \'60 minutes\',now()+interval \'8 hours\')',(token_hash(token),row[0],ip))
        ctx['conn'].execute('DELETE FROM admin_sessions WHERE account_id=%s AND (revoked_at IS NOT NULL OR expires_at<now())',(row[0],))
        actor={'id':row[0],'username':row[1],'role':row[3]}; _audit(ctx,actor,'admin.login',{})
    return 200,{'token':token,'expires_in':3600,'role':row[3],'account_id':row[0]}


def _admin_attempt(conn,identifier,ip):
    ident=str(identifier).lower()[:128]
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(f'admin-login:{ident}:{ip}',))
        n=conn.execute("SELECT count(*) FROM auth_attempts WHERE action='admin_login' AND (identifier=%s OR ip=%s::inet) AND attempted_at>now()-interval '15 minutes'",(ident,ip)).fetchone()[0]
        if n>=8: return False
        conn.execute("INSERT INTO auth_attempts(ip,identifier,action) VALUES(%s::inet,%s,'admin_login')",(ip,ident)); return True


def logout(body,ctx):
    actor=_actor(ctx,READ)
    if not actor: return 401,{'error':'unauthorized'}
    auth=ctx.get('authorization','')
    if auth.startswith('Bearer '): ctx['conn'].execute('UPDATE admin_sessions SET revoked_at=now() WHERE token_hash=%s',(token_hash(auth[7:]),))
    if actor['id']: _audit(ctx,actor,'admin.logout',{})
    return 200,{'ok':True}


def password(body,ctx):
    actor,err=_need(ctx,READ)
    if err:return err
    value=body.get('password')
    if not isinstance(value,str) or len(value)<14:return 400,{'error':'admin_password_too_short','message':'задайте пароль не короче 14 символов'}
    if actor['id'] is None:return 400,{'error':'emergency_token_no_password'}
    ctx['conn'].execute('UPDATE accounts SET password_hash=%s WHERE id=%s',(hash_password(value),actor['id'])); _audit(ctx,actor,'admin.password',{},target=actor['id'],old={'password_changed':False},new={'password_changed':True}); return 200,{'ok':True}


def overview(body,ctx):
    actor,err=_need(ctx,READ)
    if err:return err
    conn=ctx['conn']; health=conn.execute('SELECT 1').fetchone()==(1,)
    last=conn.execute('SELECT day_index,duration_ms,error,finished_at FROM game_ticks ORDER BY day_index DESC LIMIT 1').fetchone()
    people=conn.execute('SELECT count(*) FROM accounts').fetchone()[0]
    registrations=conn.execute("SELECT count(*) FROM accounts WHERE created_at>=now()-interval '1 day'").fetchone()[0]
    online=conn.execute("SELECT count(*) FROM presence WHERE seen_at>=now()-interval '90 seconds'").fetchone()[0]
    peak=conn.execute("SELECT COALESCE(max(peak),0) FROM presence_daily_peak WHERE day=(now() AT TIME ZONE 'Asia/Yekaterinburg')::date").fetchone()[0]
    enterprises=conn.execute("SELECT count(*) FROM enterprises WHERE sold_at IS NULL").fetchone()[0] if _table(conn,'enterprises') else 0
    parcels=conn.execute("SELECT count(*) FROM world_parcels WHERE owner_kind='player'").fetchone()[0] if _table(conn,'world_parcels') else 0
    system_balance=conn.execute("SELECT COALESCE(sum(balance),0) FROM ledger_accounts WHERE kind='system'").fetchone()[0]
    return 200,{'version':os.getenv('LUNEX_VERSION','v2.1.0-dev'),'sha':os.getenv('LUNEX_SHA','unknown'),'uptime_seconds':int(time.monotonic()-STARTED),'database':'ok' if health else 'down','pool':ctx['pool'].get_stats() if ctx.get('pool') else {},'last_tick':{'day':last[0],'duration_ms':last[1],'error':last[2],'at':last[3].isoformat() if last[3] else None} if last else None,'online':online,'peak_24h':peak,'players':people,'registrations_24h':registrations,'enterprises':enterprises,'owned_parcels':parcels,'system_balance':system_balance,'reconcile':reconcile(conn),'errors_24h':conn.execute("SELECT count(*) FROM game_ticks WHERE error IS NOT NULL AND started_at>=now()-interval '1 day'").fetchone()[0]}


def _table(conn,name): return conn.execute('SELECT to_regclass(%s)',(name,)).fetchone()[0] is not None


def flags(body,ctx):
    actor,err=_need(ctx,READ)
    if err:return err
    current=settings.read_settings(ctx['conn'],ctx['registry'].flags,ctx['registry'].flag_constraints)
    meta={k:{'description':f'Настройка {k}','bounds':ctx['registry'].flag_constraints.get(k)} for k in current}
    return 200,{'flags':current,'defaults':ctx['registry'].flags,'bounds':ctx['registry'].flag_constraints,'metadata':meta}

get_settings=flags


def update_settings(body,ctx):
    actor,err=_need(ctx,WRITE_SETTINGS)
    if err:return err
    key, value = body.get('key'), body.get('value')
    try:
        before = settings.read_settings(ctx['conn'],ctx['registry'].flags,ctx['registry'].flag_constraints).get(key)
        result=settings.change(ctx['conn'],key,value,body.get('apply_at','now'),actor['username'],ctx['registry'].flags,ctx['registry'].flag_constraints)
    except ValueError as exc:return 400,{'error':str(exc),'message':'значение вне допустимых границ или неверный тип'}
    _audit(ctx,actor,'setting.change',result,old={'key':key,'value':before},new={'key':key,'value':value})
    return 200,result


def revisions(body,ctx):
    actor,err=_need(ctx,READ)
    if err:return err
    rows=ctx['conn'].execute('SELECT revision,key,new_value,apply_at,effective_month,actor,created_at FROM runtime_revisions ORDER BY revision DESC LIMIT 100').fetchall()
    return 200,{'items':[{'revision':r[0],'key':r[1],'value':r[2],'apply_at':r[3],'effective_month':r[4],'actor':r[5],'at':r[6].isoformat()} for r in rows]}


def undo(body,ctx):
    actor,err=_need(ctx,WRITE_SETTINGS)
    if err:return err
    try: result=settings.rollback(ctx['conn'],int(body.get('revision')),actor['username'],ctx['registry'].flags,ctx['registry'].flag_constraints)
    except (TypeError,ValueError) as exc:return 400,{'error':str(exc)}
    _audit(ctx,actor,'setting.rollback',{'revision':body.get('revision')}); return 200,result


def audit(body,ctx):
    actor,err=_need(ctx,READ)
    if err:return err
    q=ctx.get('query',{}); clauses=[]; args=[]
    if _query(ctx,'action'):clauses.append('action=%s');args.append(_query(ctx,'action'))
    if _query(ctx,'admin'):clauses.append('actor=%s');args.append(_query(ctx,'admin'))
    if _query(ctx,'player'):
        clauses.append('target_account_id=%s');args.append(int(_query(ctx,'player')))
    where=(' WHERE '+' AND '.join(clauses)) if clauses else ''
    try: page=max(1,int(_query(ctx,'page','1'))); limit=min(100,max(1,int(_query(ctx,'limit','50'))))
    except ValueError:return 400,{'error':'invalid_pagination'}
    rows=ctx['conn'].execute('SELECT id,actor,actor_role,action,target_account_id,payload,ip,old_value,new_value,created_at FROM audit'+where+' ORDER BY id DESC LIMIT %s OFFSET %s',(*args,limit,(page-1)*limit)).fetchall()
    return 200,{'page':page,'limit':limit,'items':[{'id':r[0],'actor':r[1],'role':r[2],'action':r[3],'player_id':r[4],'payload':r[5],'ip':str(r[6]) if r[6] else None,'old':r[7],'new':r[8],'at':r[9].isoformat()} for r in rows]}


def players(body,ctx):
    actor,err=_need(ctx,READ)
    if err:return err
    q=_query(ctx,'q','').strip(); page=max(1,int(_query(ctx,'page','1'))); limit=min(100,max(1,int(_query(ctx,'limit','25')))); like='%'+q+'%'
    rows=ctx['conn'].execute('SELECT id,username,email,role,is_blocked,created_at FROM accounts WHERE username ILIKE %s OR COALESCE(email,\'\') ILIKE %s ORDER BY id DESC LIMIT %s OFFSET %s',(like,like,limit,(page-1)*limit)).fetchall()
    return 200,{'page':page,'limit':limit,'items':[{'id':r[0],'username':r[1],'email':r[2],'role':r[3],'blocked':r[4],'registered_at':r[5].isoformat()} for r in rows]}


def player_detail(body,ctx):
    actor,err=_need(ctx,READ)
    if err:return err
    pid=int(ctx['path_params']['id']); row=ctx['conn'].execute('SELECT id,username,email,role,is_blocked,created_at FROM accounts WHERE id=%s',(pid,)).fetchone()
    if not row:return 404,{'error':'not_found'}
    wallet=ctx['conn'].execute('SELECT balance FROM ledger_accounts WHERE account_key=%s',('player:'+row[1].lower(),)).fetchone()
    enterprises=[]
    if _table(ctx['conn'],'enterprises'): enterprises=[{'id':x[0],'name':x[1],'city_id':x[2],'running':x[3]} for x in ctx['conn'].execute('SELECT id,name,city_id,running FROM enterprises WHERE owner_id=%s AND sold_at IS NULL',(pid,)).fetchall()]
    parcels=ctx['conn'].execute("SELECT px,py,city_id FROM world_parcels WHERE owner_kind='player' AND owner_ref=%s",(str(pid),)).fetchall() if _table(ctx['conn'],'world_parcels') else []
    return 200,{'id':row[0],'username':row[1],'email':row[2],'role':row[3],'blocked':row[4],'registered_at':row[5].isoformat(),'wallet':wallet[0] if wallet else 0,'enterprises':enterprises,'parcels':[{'px':x[0],'py':x[1],'city_id':x[2]} for x in parcels]}


def block_player(body,ctx):
    actor,err=_need(ctx,WRITE_PLAYERS)
    if err:return err
    pid=int(ctx['path_params']['id']); reason=body.get('reason'); until=body.get('until')
    if not isinstance(reason,str) or not reason.strip():return 400,{'error':'reason_required'}
    with ctx['conn'].transaction():
        row=ctx['conn'].execute('UPDATE accounts SET is_blocked=true, blocked_until=%s, block_reason=%s WHERE id=%s RETURNING username',(until,reason,pid)).fetchone()
        if not row:return 404,{'error':'not_found'}
        ctx['conn'].execute('UPDATE sessions SET revoked_at=now() WHERE account_id=%s',(pid,)); ctx['conn'].execute('UPDATE admin_sessions SET revoked_at=now() WHERE account_id=%s',(pid,)); _audit(ctx,actor,'player.block',{'reason':reason,'until':until},target=pid,old={'blocked':False},new={'blocked':True,'until':until})
    return 200,{'ok':True,'blocked_until':until}


def unblock_player(body,ctx):
    actor,err=_need(ctx,WRITE_PLAYERS)
    if err:return err
    pid=int(ctx['path_params']['id']); row=ctx['conn'].execute('UPDATE accounts SET is_blocked=false, blocked_until=NULL, block_reason=NULL WHERE id=%s RETURNING id',(pid,)).fetchone()
    if not row:return 404,{'error':'not_found'}
    _audit(ctx,actor,'player.unblock',{},target=pid,old={'blocked':True},new={'blocked':False}); return 200,{'ok':True}


def revoke_sessions(body,ctx):
    actor,err=_need(ctx,WRITE_PLAYERS)
    if err:return err
    pid=body.get('player_id')
    if pid is None:return 400,{'error':'player_id_required'}
    ctx['conn'].execute('UPDATE sessions SET revoked_at=now() WHERE account_id=%s',(int(pid),)); ctx['conn'].execute('UPDATE admin_sessions SET revoked_at=now() WHERE account_id=%s',(int(pid),)); _audit(ctx,actor,'player.sessions_revoke',{},target=int(pid),old={'revoked':False},new={'revoked':True}); return 200,{'ok':True}


def compensate(body,ctx):
    actor,err=_need(ctx,WRITE_PLAYERS)
    if err:return err
    pid=int(ctx['path_params']['id']); amount=body.get('amount'); reason=body.get('reason'); ticket=body.get('ticket'); request_id=body.get('request_id')
    if isinstance(amount,bool) or not isinstance(amount,int) or amount==0 or not isinstance(reason,str) or not reason.strip() or not isinstance(ticket,str) or not ticket.strip() or not isinstance(request_id,str): return 400,{'error':'amount_reason_ticket_request_required'}
    if actor['role']=='support':
        limit=ctx['conn'].execute("SELECT value FROM runtime_config WHERE key='support_compensation_limit'").fetchone(); max_amount=int(limit[0]) if limit else 100000
        if abs(amount)>max_amount:return 403,{'error':'support_limit_exceeded'}
    row=ctx['conn'].execute('SELECT username FROM accounts WHERE id=%s',(pid,)).fetchone()
    if not row:return 404,{'error':'not_found'}
    treasury=ledger_account(ctx['conn'],'system:treasury'); wallet=ledger_account(ctx['conn'],'player:'+row[0].lower(),'player',pid)
    before=ctx['conn'].execute('SELECT balance FROM ledger_accounts WHERE id=%s',(wallet,)).fetchone()[0]
    try: tx=ledger_transfer(ctx['conn'],request_id,treasury,wallet,amount) if amount>0 else ledger_transfer(ctx['conn'],request_id,wallet,treasury,-amount)
    except ValueError as exc:return 400,{'error':str(exc)}
    after=ctx['conn'].execute('SELECT balance FROM ledger_accounts WHERE id=%s',(wallet,)).fetchone()[0]
    _audit(ctx,actor,'player.compensate',{'request_id':request_id,'amount':amount,'reason':reason,'ticket':ticket},target=pid,old={'wallet':before},new={'wallet':after})
    return 200,{'ok':True,'transfer_id':tx}


def roles(body,ctx):
    actor,err=_need(ctx,ALL)
    if err:return err
    pid=body.get('player_id'); role=body.get('role'); confirm=body.get('confirm')
    if not isinstance(pid,int) or role not in ROLES+('player','developer') or confirm is not True:return 400,{'error':'подтвердите выдачу роли'}
    old_row=ctx['conn'].execute('SELECT username,role FROM accounts WHERE id=%s',(pid,)).fetchone()
    if not old_row:return 404,{'error':'not_found'}
    row=ctx['conn'].execute('UPDATE accounts SET role=%s WHERE id=%s RETURNING username,role',(role,pid)).fetchone()
    if not row:return 404,{'error':'not_found'}
    _audit(ctx,actor,'account.role',{'role':role},target=pid,old={'role':old_row[1]},new={'role':role}); return 200,{'ok':True,'username':row[0],'role':row[1]}


def block(body,ctx):
    actor,err=_need(ctx,WRITE_PLAYERS)
    if err:return err
    username=body.get('username'); blocked=body.get('blocked')
    row=ctx['conn'].execute('SELECT id FROM accounts WHERE lower(username)=lower(%s)',(username,)).fetchone()
    if not row:return 404,{'error':'not_found'}
    return block_player({'reason':'legacy admin block'},dict(ctx,path_params={'id':str(row[0])})) if blocked else unblock_player({},dict(ctx,path_params={'id':str(row[0])}))
