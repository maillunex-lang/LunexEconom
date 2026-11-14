"""Server-authoritative money: double-entry ledger shared by SQLite and PostgreSQL.

Amounts are integer roubles. Every transaction has entries that sum to zero.
Player wallets can never go below zero; system accounts (treasury, construction
sink) are the counterparties and may be negative/positive.
All functions run inside the caller's database transaction; `ph` is the SQL
placeholder style ("?" for sqlite3, "%s" for psycopg).
"""
import uuid

CURRENCY = "RUB"
START_CAPITAL = 1_000_000
BUILD_COST = {"farm": 120_000, "mine": 300_000, "factory": 450_000}
ROAD_CELL_COST = 5_000
TREASURY = "system:treasury"
CONSTRUCTION = "system:construction"

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS wallets(account TEXT PRIMARY KEY, balance BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS ledger_tx(id TEXT PRIMARY KEY, kind TEXT NOT NULL, memo TEXT NOT NULL, created BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS ledger_entries(tx_id TEXT NOT NULL REFERENCES ledger_tx(id), account TEXT NOT NULL, amount BIGINT NOT NULL, PRIMARY KEY(tx_id, account))",
)


def player_account(owner):
    return "player:" + owner


def build_cost(kind, road_cells):
    return BUILD_COST[kind] + ROAD_CELL_COST * road_cells


def terms():
    return {"currency": CURRENCY, "start_capital": START_CAPITAL,
            "building_costs": dict(BUILD_COST), "road_cell_cost": ROAD_CELL_COST}


def _add_balance(db, ph, account, delta):
    db.execute("INSERT INTO wallets(account,balance) VALUES(%s,%s) ON CONFLICT(account) DO UPDATE SET balance=wallets.balance+%s".replace("%s", ph),
               (account, delta, delta))


def post(db, ph, kind, memo, entries, now):
    """Record one balanced transaction and update wallet balances."""
    if sum(a for _, a in entries) != 0 or len({acc for acc, _ in entries}) != len(entries):
        raise ValueError("unbalanced ledger transaction")
    tx_id = uuid.uuid4().hex
    db.execute("INSERT INTO ledger_tx(id,kind,memo,created) VALUES(%s,%s,%s,%s)".replace("%s", ph), (tx_id, kind, memo, now))
    for account, amount in entries:
        db.execute("INSERT INTO ledger_entries(tx_id,account,amount) VALUES(%s,%s,%s)".replace("%s", ph), (tx_id, account, amount))
        _add_balance(db, ph, account, amount)
    return tx_id


def balance(db, ph, owner):
    row = db.execute("SELECT balance FROM wallets WHERE account=%s".replace("%s", ph), (player_account(owner),)).fetchone()
    return row[0] if row else None


def ensure_wallet(db, ph, owner, now):
    """Create the wallet with the starting capital on first use (idempotent)."""
    account = player_account(owner)
    cur = db.execute("INSERT INTO wallets(account,balance) VALUES(%s,0) ON CONFLICT(account) DO NOTHING".replace("%s", ph), (account,))
    if cur.rowcount == 1:
        post(db, ph, "start_capital", "Стартовый капитал", [(account, START_CAPITAL), (TREASURY, -START_CAPITAL)], now)
    return balance(db, ph, owner)


def charge_build(db, ph, owner, kind, road_cells, now):
    """Charge for a building plus its access road. Returns (ok, cost, balance)."""
    cost = build_cost(kind, road_cells)
    current = ensure_wallet(db, ph, owner, now)
    if current < cost:
        return False, cost, current
    account = player_account(owner)
    memo = "Строительство: %s" % kind
    if road_cells:
        memo += " + дорога %d кл." % road_cells
    post(db, ph, "build", memo, [(account, -cost), (CONSTRUCTION, cost)], now)
    return True, cost, current - cost


def history(db, ph, owner, limit=20):
    rows = db.execute(
        "SELECT t.kind,t.memo,t.created,e.amount FROM ledger_entries e JOIN ledger_tx t ON t.id=e.tx_id "
        "WHERE e.account=%s ORDER BY t.created DESC, t.id DESC LIMIT %s".replace("%s", ph),
        (player_account(owner), limit)).fetchall()
    return [{"kind": k, "memo": m, "time": c, "amount": a} for k, m, c, a in rows]


def wallet(db, ph, owner, now):
    bal = ensure_wallet(db, ph, owner, now)
    return {"ok": True, "balance": bal, "currency": CURRENCY, "transactions": history(db, ph, owner)}
