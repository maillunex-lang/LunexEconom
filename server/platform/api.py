"""HTTP handlers share a request-scoped PostgreSQL transaction."""
import os
from .security import hash_password, verify_password, new_token, token_hash


def health(body, ctx):
    ok = ctx['conn'].execute('SELECT 1').fetchone() == (1,)
    return (200 if ok else 503), {'ok': ok, 'database': 'ok' if ok else 'down', 'version': os.getenv('LUNEX_VERSION', 'v2.0.0-dev'), 'sha': os.getenv('LUNEX_SHA', 'unknown')}


def register(body, ctx):
    username, password = body.get('username'), body.get('password')
    if not isinstance(username, str) or not 3 <= len(username) <= 40 or not username.replace('_', '').isalnum():
        return 400, {'error': 'invalid_username'}
    try:
        hashed = hash_password(password)
    except (ValueError, AttributeError):
        return 400, {'error': 'invalid_password'}
    if not ctx['settings'].get('registration_enabled'):
        return 403, {'error': 'registration_disabled'}
    with ctx['conn'].transaction():
        row = ctx['conn'].execute('INSERT INTO accounts(username,password_hash,role) VALUES(%s,%s,%s) ON CONFLICT (username) DO NOTHING RETURNING id', (username, hashed, 'player')).fetchone()
    if row is None:
        return 409, {'error': 'username_taken'}
    return 201, {'id': row[0], 'username': username, 'role': 'player'}


def login(body, ctx):
    username, password = body.get('username'), body.get('password')
    if not isinstance(username, str) or not isinstance(password, str):
        return 400, {'error': 'invalid_credentials'}
    row = ctx['conn'].execute('SELECT id,password_hash,role FROM accounts WHERE username = %s', (username,)).fetchone()
    if not row or not verify_password(password, row[1]):
        return 401, {'error': 'invalid_credentials'}
    token = new_token()
    with ctx['conn'].transaction():
        ctx['conn'].execute("INSERT INTO sessions(token_hash,account_id,expires_at) VALUES(%s,%s, now() + interval '30 days')", (token_hash(token), row[0]))
    return 200, {'token': token, 'role': row[2], 'account_id': row[0]}


def me(body, ctx):
    auth = ctx.get('authorization', '')
    if not auth.startswith('Bearer '):
        return 401, {'error': 'unauthorized'}
    token = auth[7:]
    if len(token) > 256:
        return 401, {'error': 'unauthorized'}
    row = ctx['conn'].execute('SELECT a.id, a.username, a.role FROM sessions s JOIN accounts a ON a.id=s.account_id WHERE s.token_hash=%s AND s.expires_at>now()', (token_hash(token),)).fetchone()
    if not row:
        return 401, {'error': 'unauthorized'}
    return 200, {'id': row[0], 'username': row[1], 'role': row[2]}


def config(body, ctx):
    row = ctx['conn'].execute('SELECT revision,payload_b64,signature FROM signed_client_config ORDER BY revision DESC LIMIT 1').fetchone()
    if row is None:
        return 503, {'error': 'config_not_signed'}
    return 200, {'schema': 1, 'revision': row[0], 'payload_b64': row[1], 'signature': row[2]}
