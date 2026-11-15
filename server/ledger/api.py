"""PostgreSQL double-entry ledger; integer RUB, idempotent, deterministic row locks."""
from __future__ import annotations
from collections import defaultdict

MAX_INT = 2**63 - 1
SYSTEM_NAMES = ('treasury', 'market', 'bank', 'upkeep', 'escrow')


def account(conn, key, kind=None, owner_id=None, allow_negative=False):
    if not isinstance(key, str) or not key or len(key) > 120:
        raise ValueError('invalid account key')
    with conn.transaction():
        if key.startswith('system:'):
            if key[7:] not in SYSTEM_NAMES:
                raise ValueError('invalid system account')
            kind, allow_negative = 'system', True
        else:
            if kind not in ('player', 'company', 'city'):
                raise ValueError('invalid account kind')
            allow_negative = False
        row = conn.execute('INSERT INTO ledger_accounts(account_key,kind,owner_id,allow_negative) VALUES(%s,%s,%s,%s) ON CONFLICT(account_key) DO UPDATE SET account_key=excluded.account_key RETURNING id', (key, kind, owner_id, allow_negative)).fetchone()
        return row[0]


def post(conn, request_id, entries):
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
        raise ValueError('invalid request_id')
    if not isinstance(entries, (list, tuple)) or len(entries) < 2 or len(entries) > 128:
        raise ValueError('invalid postings')
    amounts = defaultdict(int)
    for entry in entries:
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            raise ValueError('invalid entry')
        account_id, amount = entry
        if isinstance(account_id, bool) or not isinstance(account_id, int) or account_id <= 0 or isinstance(amount, bool) or not isinstance(amount, int) or not -MAX_INT <= amount <= MAX_INT or amount == 0:
            raise ValueError('invalid posting amount')
        amounts[account_id] += amount
    if len(amounts) < 2 or any(amount == 0 or not -MAX_INT <= amount <= MAX_INT for amount in amounts.values()) or sum(amounts.values()) != 0:
        raise ValueError('nonzero or malformed journal')
    expected = sorted(amounts.items())
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', (request_id,))
        previous = conn.execute('SELECT t.id,e.account_id,e.amount FROM ledger_transfers t JOIN ledger_entries e ON e.transfer_id=t.id WHERE t.request_id=%s ORDER BY e.account_id', (request_id,)).fetchall()
        if previous:
            if sorted((r[1], r[2]) for r in previous) != expected:
                raise ValueError('request_id reused with different postings')
            return previous[0][0]
        ids = sorted(amounts)
        rows = conn.execute('SELECT id,balance,allow_negative FROM ledger_accounts WHERE id=ANY(%s) ORDER BY id FOR UPDATE', (ids,)).fetchall()
        if len(rows) != len(ids):
            raise ValueError('unknown account')
        for aid, balance, allow_negative in rows:
            result = balance + amounts[aid]
            if not -MAX_INT <= result <= MAX_INT or (result < 0 and not allow_negative):
                raise ValueError('insufficient balance')
        txid = conn.execute('INSERT INTO ledger_transfers(request_id) VALUES(%s) RETURNING id', (request_id,)).fetchone()[0]
        for aid, delta in expected:
            conn.execute('INSERT INTO ledger_entries(transfer_id,account_id,amount) VALUES(%s,%s,%s)', (txid, aid, delta))
            conn.execute('UPDATE ledger_accounts SET balance=balance+%s WHERE id=%s', (delta, aid))
        return txid


def transfer(conn, request_id, from_id, to_id, amount):
    if isinstance(amount, bool) or not isinstance(amount, int) or not 0 < amount <= MAX_INT or from_id == to_id:
        raise ValueError('invalid transfer')
    return post(conn, request_id, [(from_id, -amount), (to_id, amount)])


def initial_capital(conn, owner_id, username, amount=1000000):
    wallet = account(conn, 'player:' + username.lower(), 'player', owner_id)
    treasury = account(conn, 'system:treasury')
    transfer(conn, 'initial-capital:' + str(owner_id), treasury, wallet, amount)
    return wallet


def reconcile(conn):
    imbalance = conn.execute('SELECT COALESCE(sum(balance),0) FROM ledger_accounts').fetchone()[0]
    mismatch = conn.execute('SELECT count(*) FROM ledger_accounts a WHERE a.balance <> COALESCE((SELECT sum(e.amount) FROM ledger_entries e WHERE e.account_id=a.id),0)').fetchone()[0]
    unbalanced = conn.execute('SELECT count(*) FROM ledger_transfers t WHERE COALESCE((SELECT sum(e.amount) FROM ledger_entries e WHERE e.transfer_id=t.id),1)<>0').fetchone()[0]
    return {'ok': imbalance == 0 and mismatch == 0 and unbalanced == 0, 'total_balance': int(imbalance), 'mismatched_accounts': mismatch, 'unbalanced_transactions': unbalanced}


def _session_account(ctx):
    from server.platform.api import authenticate
    actor = authenticate(ctx)
    if not actor:
        return None
    row = ctx['conn'].execute('SELECT id,balance FROM ledger_accounts WHERE account_key=%s', ('player:'+actor['username'].lower(),)).fetchone()
    return row


def balance(body, ctx):
    row = _session_account(ctx)
    if row is None:
        return 401, {'error':'unauthorized'}
    return 200, {'account_id':row[0], 'balance':row[1], 'currency':'RUB', 'unit':'game_ruble'}


def history(body, ctx):
    row = _session_account(ctx)
    if row is None:
        return 401, {'error':'unauthorized'}
    query = ctx.get('query',{})
    try:
        page = int(query.get('page',['1'])[0]); limit = int(query.get('limit',['25'])[0])
    except (TypeError, ValueError):
        return 400, {'error':'invalid_pagination'}
    if not 1 <= page <= 100000 or not 1 <= limit <= 100:
        return 400, {'error':'invalid_pagination'}
    rows = ctx['conn'].execute('SELECT t.id,t.request_id,t.created_at,e.amount FROM ledger_entries e JOIN ledger_transfers t ON t.id=e.transfer_id WHERE e.account_id=%s ORDER BY t.id DESC LIMIT %s OFFSET %s', (row[0], limit,(page-1)*limit)).fetchall()
    return 200, {'page':page,'limit':limit,'items':[{'id':r[0],'request_id':r[1],'at':r[2].isoformat(),'amount':r[3]} for r in rows]}
