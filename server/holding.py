"""Holding ledger: subsidiaries are balance-sheet owners, not simulated players.

The established production engine still settles the parent company.  Subsidiary
balances and internal transfers are independently posted, never synthesized as
operating income. All routines are caller-transaction-bound (SQLite/Postgres).
"""
import re
import time
import uuid

import economy
import bank

_NAME = re.compile(r"^[^\x00-\x1f]{1,80}$")


def _q(sql, ph):
    return sql.replace('%s', ph)


def ensure(db, ph):
    for sql in (
        "CREATE TABLE IF NOT EXISTS holdings(owner TEXT PRIMARY KEY, name TEXT NOT NULL, founded_month BIGINT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS holding_subs(id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL, created BIGINT NOT NULL, UNIQUE(owner,name))",
        "CREATE INDEX IF NOT EXISTS holding_subs_owner ON holding_subs(owner)",
        "CREATE TABLE IF NOT EXISTS holding_transfers(id TEXT PRIMARY KEY, owner TEXT NOT NULL, src TEXT NOT NULL, dst TEXT NOT NULL, amount BIGINT NOT NULL, created BIGINT NOT NULL, tx_id TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS enterprise_settings(object_id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL DEFAULT '', price INTEGER, price_rule TEXT NOT NULL DEFAULT 'market', min_stock TEXT NOT NULL DEFAULT '{}', buy_limit BIGINT NOT NULL DEFAULT 0, managers TEXT NOT NULL DEFAULT '{}')",
        "CREATE TABLE IF NOT EXISTS auto_months(owner TEXT NOT NULL, month_index BIGINT NOT NULL, PRIMARY KEY(owner,month_index))",
    ):
        db.execute(sql)


def root_account(owner):
    return economy.player_account(owner)


def subsidiary_account(sub_id):
    return 'holding:sub:' + sub_id


def create(db, ph, owner, name, month=0):
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError('invalid_name')
    db.execute(_q('INSERT INTO holdings(owner,name,founded_month) VALUES(%s,%s,%s) ON CONFLICT(owner) DO NOTHING', ph),
               (owner, name, month))
    return db.execute(_q('SELECT name,founded_month FROM holdings WHERE owner=%s', ph), (owner,)).fetchone()


def add_subsidiary(db, ph, owner, name, now=None, sub_id=None):
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError('invalid_name')
    if not db.execute(_q('SELECT 1 FROM holdings WHERE owner=%s', ph), (owner,)).fetchone():
        raise ValueError('holding_missing')
    sub_id = sub_id or uuid.uuid4().hex
    db.execute(_q('INSERT INTO holding_subs(id,owner,name,created) VALUES(%s,%s,%s,%s)', ph),
               (sub_id, owner, name, int(now if now is not None else time.time())))
    db.execute(_q('INSERT INTO wallets(account,balance) VALUES(%s,0) ON CONFLICT(account) DO NOTHING', ph), (subsidiary_account(sub_id),))
    return sub_id


def accounts(db, ph, owner):
    result = [root_account(owner)]
    result.extend(subsidiary_account(row[0]) for row in db.execute(_q('SELECT id FROM holding_subs WHERE owner=%s ORDER BY id', ph), (owner,)))
    return result


def transfer(db, ph, owner, src, dst, amount, request_id, now):
    try:
        uuid.UUID(request_id)
    except (ValueError, TypeError, AttributeError):
        return 400, {'error': 'invalid_request_id'}
    if type(amount) is not int or amount <= 0 or src == dst:
        return 400, {'error': 'invalid_transfer'}
    previous = db.execute(_q('SELECT src,dst,amount,tx_id FROM holding_transfers WHERE id=%s AND owner=%s', ph), (request_id, owner)).fetchone()
    if previous:
        return (200, {'ok': True, 'replayed': True, 'tx_id': previous[3]}) if previous[:3] == (src, dst, amount) else (409, {'error': 'request_id_conflict'})
    allowed = set(accounts(db, ph, owner))
    if src not in allowed or dst not in allowed:
        return 403, {'error': 'not_owned'}
    available = db.execute(_q('SELECT balance FROM wallets WHERE account=%s', ph), (src,)).fetchone()
    if not available or int(available[0]) < amount:
        return 402, {'error': 'insufficient_funds'}
    tx = economy.post(db, ph, 'holding_transfer', 'Внутренний перевод холдинга', [(src, -amount), (dst, amount)], now)
    db.execute(_q('INSERT INTO holding_transfers VALUES(%s,%s,%s,%s,%s,%s,%s)', ph), (request_id, owner, src, dst, amount, now, tx))
    return 201, {'ok': True, 'tx_id': tx}


def consolidated(db, ph, owner, limit=6):
    """Only external activity affects profit; intra-group transfers are eliminated."""
    accts = accounts(db, ph, owner)
    marks = ','.join([ph] * len(accts))
    cash = int(db.execute('SELECT COALESCE(SUM(balance),0) FROM wallets WHERE account IN (' + marks + ')', tuple(accts)).fetchone()[0])
    reports = db.execute(_q('SELECT month_index,revenue,input_cost,upkeep,profit FROM company_reports WHERE owner=%s ORDER BY month_index DESC LIMIT %s', ph), (owner, limit)).fetchall()
    monthly = [{'month_index': int(m), 'revenue': int(r), 'input_cost': int(i), 'upkeep': int(u), 'profit': int(p)}
               for m, r, i, u, p in reports]
    # A balanced internal journal entry is not sales, spending or consolidated profit.
    return {'cash': cash, 'profit_month': monthly[0]['profit'] if monthly else 0, 'history': monthly,
            'subsidiaries': len(accts) - 1, 'internal_revenue': 0, 'internal_profit': 0}


def overview(db, ph, owner):
    import production
    rep = consolidated(db, ph, owner)
    st = production.company_view(db, ph, owner)
    debt = bank.balance(db, ph, owner)
    assets = sum(economy.BUILD_COST.get(kind, 0) for kind, in db.execute(_q('SELECT kind FROM building_ops WHERE owner=%s', ph), (owner,)))
    return {'cash': rep['cash'], 'profit_month': rep['profit_month'], 'reports': rep['history'],
            'assets': assets, 'net_assets': rep['cash'] + assets - debt - st['arrears'],
            'debts': {'loans': debt, 'arrears': st['arrears'], 'taxes': st['tax_owed']},
            'payments': [{'kind': key, 'amount': st[key]} for key in ('wages_owed','input_owed','maint_owed','tax_owed') if st[key] > 0],
            'forecast_next_month': None, 'subsidiaries': rep['subsidiaries']}