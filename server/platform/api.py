"""Platform HTTP handlers with rotating refresh sessions and PostgreSQL rate limits."""
import os
import ipaddress
import re
import time
from uuid import uuid4
from .security import hash_password, verify_password, new_token, token_hash

USERNAME = re.compile(r'^[A-Za-z0-9_]{3,24}$')
EMAIL = re.compile(r'^[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}$')
STARTED = time.monotonic()


def _ip(ctx):
    peer=ctx.get('remote_addr','127.0.0.1')
    if not isinstance(peer,str):
        return '127.0.0.1'
    try:
        ipaddress.ip_address(peer)
        if peer in ('127.0.0.1','::1') and os.getenv('LUNEX_TRUST_PROXY_REAL_IP')=='1':
            claimed=ctx.get('real_ip','')
            if isinstance(claimed,str):
                ipaddress.ip_address(claimed)
                return claimed
    except ValueError:
        pass
    return peer[:45]


def _attempt(conn, action, identifier, ip, threshold=8):
    identifier = str(identifier).lower()[:128]
    ip = ip or '127.0.0.1'
    with conn.transaction():
        # Advisory locks serialize rate checks for account AND IP under concurrent load.
        for key in sorted((f'{action}:acct:{identifier}',f'{action}:ip:{ip}')):
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', (key,))
        attempts=conn.execute("SELECT count(*) FROM auth_attempts WHERE action=%s AND identifier=%s AND attempted_at>now()-interval '15 minutes'",(action,identifier)).fetchone()[0]
        by_ip=conn.execute("SELECT count(*) FROM auth_attempts WHERE action=%s AND ip=%s::inet AND attempted_at>now()-interval '15 minutes'",(action,ip)).fetchone()[0]
        ip_limit=120 if action=='login' else 10
        if attempts>=threshold or by_ip>=ip_limit:
            return False
        conn.execute('INSERT INTO auth_attempts(ip,identifier,action) VALUES(%s::inet,%s,%s)', (ip,identifier,action))
        return True


def _clear_failures(conn, action, identifier, ip):
    conn.execute('DELETE FROM auth_attempts WHERE action=%s AND identifier=%s', (action,identifier.lower()[:128]))


def authenticate(ctx, track=True):
    auth = ctx.get('authorization','')
    if not isinstance(auth,str) or not auth.startswith('Bearer ') or len(auth)>300:
        return None
    value = auth[7:]
    row = ctx['conn'].execute('SELECT a.id,a.username,a.role,a.is_blocked,a.email FROM sessions s JOIN accounts a ON a.id=s.account_id WHERE s.token_hash=%s AND s.expires_at>now() AND s.revoked_at IS NULL', (token_hash(value),)).fetchone()
    if not row or row[3]:
        return None
    if track:
        updated=ctx['conn'].execute("INSERT INTO presence(account_id,client_version) VALUES(%s,%s) ON CONFLICT(account_id) DO UPDATE SET seen_at=now(),client_version=excluded.client_version WHERE presence.seen_at<=now()-interval '30 seconds' RETURNING account_id", (row[0],str(ctx.get('client_version',''))[:80])).fetchone()
        if updated:
            ctx['conn'].execute("INSERT INTO presence_daily_peak(day,peak) VALUES((now() AT TIME ZONE 'Asia/Yekaterinburg')::date,(SELECT count(*) FROM presence WHERE seen_at>=now()-interval '90 seconds')) ON CONFLICT(day) DO UPDATE SET peak=GREATEST(presence_daily_peak.peak,excluded.peak)")
    return {'id':row[0],'username':row[1],'role':row[2],'email':row[4]}


def health(body, ctx):
    ok = ctx['conn'].execute('SELECT 1').fetchone() == (1,)
    pool = ctx.get('pool')
    stats = pool.get_stats() if pool else {}
    tick = ctx['conn'].execute('SELECT day_index,duration_ms,finished_at,error FROM game_ticks ORDER BY day_index DESC LIMIT 1').fetchone()
    return (200 if ok else 503), {'ok':ok,'database':'ok' if ok else 'down','version':os.getenv('LUNEX_VERSION','v2.1.0-dev'),'sha':os.getenv('LUNEX_SHA','unknown'),'pool':{'size':stats.get('pool_size',0),'available':stats.get('pool_available',0),'waiting':stats.get('requests_waiting',0)},'tick':{'day_index':tick[0],'duration_ms':tick[1],'finished_at':tick[2].isoformat() if tick[2] else None,'error':tick[3]} if tick else None}


def register(body, ctx):
    username,password,email = body.get('username'),body.get('password'),body.get('email')
    if not isinstance(username,str) or not USERNAME.fullmatch(username):
        return 400, {'error':'invalid_username'}
    if not isinstance(email,str) or len(email)>254 or not EMAIL.fullmatch(email):
        return 400, {'error':'invalid_email'}
    email = email.lower()
    if not isinstance(password,str) or not 10 <= len(password) <= 256:
        return 400, {'error':'invalid_password'}
    if not ctx['settings'].get('registration_enabled'):
        return 403, {'error':'registration_disabled'}
    if not _attempt(ctx['conn'],'register',email,_ip(ctx),10):
        return 429, {'error':'rate_limited'}
    hashed=hash_password(password)
    with ctx['conn'].transaction():
        row = ctx['conn'].execute('INSERT INTO accounts(username,email,password_hash,role) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id', (username,email,hashed,'player')).fetchone()
        if row is None:
            return 409, {'error':'account_exists'}
        from server.ledger.api import initial_capital
        initial_capital(ctx['conn'],row[0],username)
        return 201, {'id':row[0],'username':username,'email':email,'role':'player'}


def _tokens(conn,account_id):
    access,refresh = new_token(),new_token()
    conn.execute("INSERT INTO sessions(token_hash,refresh_hash,account_id,expires_at,refresh_expires_at) VALUES(%s,%s,%s,now()+interval '30 minutes',now()+interval '30 days')", (token_hash(access),token_hash(refresh),account_id))
    return access,refresh


def login(body, ctx):
    identifier,password = body.get('username') or body.get('email'),body.get('password')
    if not isinstance(identifier,str) or not isinstance(password,str) or len(identifier)>254:
        return 400, {'error':'invalid_credentials'}
    if not _attempt(ctx['conn'],'login',identifier,_ip(ctx),8):
        return 429, {'error':'rate_limited'}
    row = ctx['conn'].execute('SELECT id,password_hash,role,is_blocked FROM accounts WHERE lower(username)=lower(%s) OR email=%s', (identifier,identifier.lower())).fetchone()
    if not row or row[3] or not verify_password(password,row[1]):
        return 401, {'error':'invalid_credentials'}
    with ctx['conn'].transaction():
        _clear_failures(ctx['conn'],'login',identifier,_ip(ctx))
        access,refresh = _tokens(ctx['conn'],row[0])
    return 200, {'token':access,'access_token':access,'refresh_token':refresh,'expires_in':1800,'role':row[2],'account_id':row[0]}


def refresh(body, ctx):
    value = body.get('refresh_token')
    if not isinstance(value,str) or len(value)>256 or len(value)<30:
        return 401, {'error':'invalid_refresh'}
    with ctx['conn'].transaction():
        row = ctx['conn'].execute('SELECT s.account_id,s.refresh_expires_at,s.revoked_at,a.is_blocked,a.role FROM sessions s JOIN accounts a ON a.id=s.account_id WHERE s.refresh_hash=%s FOR UPDATE OF s', (token_hash(value),)).fetchone()
        if not row or row[2] or row[3] or row[1] is None:
            return 401, {'error':'invalid_refresh'}
        valid = ctx['conn'].execute('SELECT %s>now()', (row[1],)).fetchone()[0]
        if not valid:
            return 401, {'error':'refresh_expired'}
        ctx['conn'].execute('UPDATE sessions SET revoked_at=now() WHERE refresh_hash=%s', (token_hash(value),))
        access,new_refresh = _tokens(ctx['conn'],row[0])
    return 200, {'token':access,'access_token':access,'refresh_token':new_refresh,'expires_in':1800,'role':row[4]}


def logout(body, ctx):
    value = body.get('refresh_token')
    actor = authenticate(ctx,track=False)
    if actor:
        ctx['conn'].execute('UPDATE sessions SET revoked_at=now() WHERE token_hash=%s AND account_id=%s', (token_hash(ctx['authorization'][7:]),actor['id']))
        return 200, {'ok':True}
    if isinstance(value,str) and 30<=len(value)<=256:
        ctx['conn'].execute('UPDATE sessions SET revoked_at=now() WHERE refresh_hash=%s', (token_hash(value),))
        return 200, {'ok':True}
    return 401, {'error':'unauthorized'}


def me(body, ctx):
    actor=authenticate(ctx)
    return (200,actor) if actor else (401,{'error':'unauthorized'})


def config(body,ctx):
    row=ctx['conn'].execute('SELECT revision,payload_b64,signature FROM signed_client_config ORDER BY revision DESC LIMIT 1').fetchone()
    if row is None:
        return 503, {'error':'config_not_signed'}
    return 200, {'schema':1,'revision':row[0],'payload_b64':row[1],'signature':row[2]}
