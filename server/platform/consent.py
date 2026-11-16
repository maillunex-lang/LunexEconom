"""Versioned consent and reversible deletion of player data."""
from uuid import uuid4
from datetime import datetime, timezone
from .security import verify_password, hash_password

CONFIRM_PHRASE = 'УДАЛИТЬ АККАУНТ'
DEFAULT_VERSION = '2026-11-16'

def version(ctx):
    value = ctx['settings'].get('consent_version', DEFAULT_VERSION)
    return value if isinstance(value,str) and 1 <= len(value) <= 64 else DEFAULT_VERSION

def required(conn, account_id, current):
    row=conn.execute('SELECT consent_version FROM accounts WHERE id=%s AND deleted_at IS NULL',(account_id,)).fetchone()
    return current if row and row[0]!=current else None

def record(conn,account_id,current):
    conn.execute('INSERT INTO account_consents(account_id,version) VALUES(%s,%s) ON CONFLICT DO NOTHING',(account_id,current))
    conn.execute('UPDATE accounts SET consent_version=%s, consent_at=(SELECT accepted_at FROM account_consents WHERE account_id=%s AND version=%s) WHERE id=%s AND deleted_at IS NULL',(current,account_id,current,account_id))

def accept(body,ctx):
    from .api import authenticate, _attempt, _ip
    actor=authenticate(ctx,track=False)
    if not actor: return 401,{'error':'unauthorized'}
    if body.get('consent_personal_data') is not True: return 400,{'error':'consent_required'}
    if not _attempt(ctx['conn'],'consent',str(actor['id']),_ip(ctx),10):
        return 429,{'error':'rate_limited'}
    current=version(ctx)
    record(ctx['conn'],actor['id'],current)
    return 200,{'ok':True,'consent_version':current}

def delete(body,ctx):
    from .api import authenticate, _attempt, _ip
    actor=authenticate(ctx,track=False)
    if not actor: return 401,{'error':'unauthorized'}
    if actor['role']!='player': return 403,{'error':'forbidden'}
    password=body.get('password')
    if not isinstance(password,str) or not 1<=len(password)<=256 or body.get('confirmation_phrase')!=CONFIRM_PHRASE:
        return 400,{'error':'delete_confirmation_required'}
    if not _attempt(ctx['conn'],'account_delete',str(actor['id']),_ip(ctx),5):
        return 429,{'error':'rate_limited'}
    row=ctx['conn'].execute('SELECT password_hash,delete_requested_at,deleted_at FROM accounts WHERE id=%s FOR UPDATE',(actor['id'],)).fetchone()
    if not row or row[2] is not None: return 401,{'error':'unauthorized'}
    if not verify_password(password,row[0]): return 401,{'error':'invalid_credentials'}
    if row[1] is None:
        ctx['conn'].execute('UPDATE accounts SET delete_requested_at=now() WHERE id=%s',(actor['id'],))
        ctx['conn'].execute("INSERT INTO audit(actor,actor_role,target_account_id,action,payload) VALUES(%s,%s,%s,%s,%s::jsonb)",('account:'+str(actor['id']),'player',actor['id'],'account.delete_requested','{}'))
    ctx['conn'].execute('UPDATE sessions SET revoked_at=now() WHERE account_id=%s AND revoked_at IS NULL',(actor['id'],))
    ctx['conn'].execute('UPDATE admin_sessions SET revoked_at=now() WHERE account_id=%s AND revoked_at IS NULL',(actor['id'],))
    due=ctx['conn'].execute("SELECT delete_requested_at+interval '7 days' FROM accounts WHERE id=%s",(actor['id'],)).fetchone()[0]
    return 200,{'ok':True,'delete_after':due.isoformat(),'cancel_on_login':True}

def finalize_pending(conn):
    """Called on daily tick. Preserve owner row, business references and ledger journal."""
    rows=conn.execute("""SELECT id,username,email FROM accounts WHERE role='player'
        AND deleted_at IS NULL AND delete_requested_at<=now()-interval '7 days'
        FOR UPDATE SKIP LOCKED""").fetchall()
    for account_id,username,email in rows:
        replacement='deleted_'+str(account_id)
        conn.execute('UPDATE ledger_accounts SET account_key=%s WHERE owner_id=%s AND account_key=%s',('player:'+replacement,account_id,'player:'+username.lower()))
        conn.execute("""UPDATE accounts SET username=%s,email=NULL,password_hash=%s,
            is_blocked=true,blocked_until=NULL,block_reason=NULL,deleted_at=now() WHERE id=%s""",
            (replacement,hash_password(uuid4().hex+uuid4().hex),account_id))
        conn.execute('UPDATE sessions SET revoked_at=now() WHERE account_id=%s AND revoked_at IS NULL',(account_id,))
        conn.execute('UPDATE admin_sessions SET revoked_at=now() WHERE account_id=%s AND revoked_at IS NULL',(account_id,))
        conn.execute('DELETE FROM auth_attempts WHERE lower(identifier)=lower(%s) OR lower(identifier)=lower(%s)',(username,email or ''))
        conn.execute("INSERT INTO audit(actor,actor_role,target_account_id,action,payload) VALUES(%s,%s,%s,%s,%s::jsonb)",('account:'+str(account_id),'player',account_id,'account.anonymized','{}'))
    return len(rows)
