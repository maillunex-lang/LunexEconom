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
BUILD_COST = {"farm": 120_000, "mine": 300_000, "factory": 450_000, "warehouse": 80_000}
ROAD_CELL_COST = 5_000
TREASURY = "system:treasury"
CONSTRUCTION = "system:construction"
MARKET_ACCOUNT = "system:market"      # buys all production at the clearing price
UPKEEP = "system:upkeep"      # sink for salaries and maintenance
MAX_SETTLE_MONTHS = 600   # months processed per call when catching up

# ---- Tunable balance tables: change numbers here, nothing else depends on them ----
# output: units per full game month; upkeep: roubles per month.
# `inputs`: raw materials consumed per full month at full capacity (bought from the market when the owner's own
# stock is short). `capacity`: units of storage a warehouse adds (shared by all products of the owner).
PRODUCTION = {
    "farm":      {"product": "honey", "output": 100, "upkeep": 8_000},
    "mine":      {"product": "oil",   "output": 40,  "upkeep": 30_000},
    "factory":   {"product": "goods", "output": 60,  "upkeep": 56_000, "inputs": {"oil": 10, "honey": 20}},
    "warehouse": {"product": None,    "output": 0,   "upkeep": 5_000,  "capacity": 400},
}
# A warehouse owner holds production back while last month's price was below reference * HOLD_BELOW
# and releases everything (stock included) once the price recovers.
HOLD_BELOW = 1.0
# Market: one world-wide market per product (regions/cities come later).
#   price = reference_price * (demand / supply) ** (1 / elasticity), clamped to [MIN_PRICE_K, MAX_PRICE_K] x reference.
#   demand = base_demand * season[calendar month] * (1 + DEMAND_GROWTH) ** month_index
# base_demand = 2 buildings' output: the world absorbs two buildings of a kind at the reference price;
# a lone first building enjoys a premium, a crowded market pushes prices (and profit) down.
MARKET = {
    "honey": {"name": "Мёд",    "reference_price": 200,  "base_demand": 200, "elasticity": 1.5,
              "season": [1.15, 1.10, 1.00, 0.95, 0.90, 0.90, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15]},
    "oil":   {"name": "Нефть",  "reference_price": 1500, "base_demand": 80,  "elasticity": 1.5,
              "season": [1.15, 1.10, 1.05, 0.95, 0.90, 0.85, 0.85, 0.90, 0.95, 1.05, 1.10, 1.15]},
    "goods": {"name": "Товары", "reference_price": 2000, "base_demand": 120, "elasticity": 1.5,
              "season": [0.95, 0.90, 0.95, 1.00, 1.00, 1.00, 1.00, 1.05, 1.05, 1.05, 1.10, 1.25]},
}
DEMAND_GROWTH = 0.005     # population/demand growth per game month
MIN_PRICE_K = 0.25
MAX_PRICE_K = 2.5

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS wallets(account TEXT PRIMARY KEY, balance BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS ledger_tx(id TEXT PRIMARY KEY, kind TEXT NOT NULL, memo TEXT NOT NULL, created BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS building_ops(object_id TEXT PRIMARY KEY, owner TEXT NOT NULL, kind TEXT NOT NULL, start_month BIGINT NOT NULL, start_permille INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS market_prices(product TEXT NOT NULL, month_index BIGINT NOT NULL, price BIGINT NOT NULL, supply BIGINT NOT NULL, demand BIGINT NOT NULL, PRIMARY KEY(product, month_index))",
    "CREATE TABLE IF NOT EXISTS world_state(id INTEGER PRIMARY KEY, processed_through BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS inventory(owner TEXT NOT NULL, product TEXT NOT NULL, qty BIGINT NOT NULL, PRIMARY KEY(owner, product))",
    "CREATE TABLE IF NOT EXISTS company_reports(owner TEXT NOT NULL, month_index BIGINT NOT NULL, revenue BIGINT NOT NULL, input_cost BIGINT NOT NULL, upkeep BIGINT NOT NULL, profit BIGINT NOT NULL, buildings INTEGER NOT NULL, PRIMARY KEY(owner, month_index))",
    "CREATE TABLE IF NOT EXISTS npc_state(owner TEXT PRIMARY KEY, acted_through BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS company_state(owner TEXT PRIMARY KEY, settled_through BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS monthly_reports(owner TEXT NOT NULL, month_index BIGINT NOT NULL, revenue BIGINT NOT NULL, upkeep BIGINT NOT NULL, profit BIGINT NOT NULL, buildings INTEGER NOT NULL, PRIMARY KEY(owner, month_index))",
    "CREATE TABLE IF NOT EXISTS ledger_entries(tx_id TEXT NOT NULL REFERENCES ledger_tx(id), account TEXT NOT NULL, amount BIGINT NOT NULL, PRIMARY KEY(tx_id, account))",
)


def player_account(owner):
    return "player:" + owner


def build_cost(kind, road_cells):
    return BUILD_COST[kind] + ROAD_CELL_COST * road_cells


def terms():
    return {"currency": CURRENCY, "start_capital": START_CAPITAL,
            "building_costs": dict(BUILD_COST), "road_cell_cost": ROAD_CELL_COST,
            "hold_below": HOLD_BELOW,
            "production": {k: {"product_id": v["product"], "product": MARKET[v["product"]]["name"] if v["product"] else "",
                               "output": v["output"], "unit_price": MARKET[v["product"]]["reference_price"] if v["product"] else 0,
                               "upkeep": v["upkeep"], "inputs": dict(v.get("inputs", {})), "capacity": v.get("capacity", 0)}
                           for k, v in PRODUCTION.items()}}


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


def demand_for(product, month):
    m = MARKET[product]
    return int(round(m["base_demand"] * m["season"][month % 12] * (1 + DEMAND_GROWTH) ** month))


def price_for(product, supply, demand):
    """Clearing price for the given supply/demand (integer roubles)."""
    m = MARKET[product]
    ref = m["reference_price"]
    if supply <= 0:
        return int(round(ref * MAX_PRICE_K))
    target = ref * (max(demand, 0) / supply) ** (1.0 / m["elasticity"])
    return int(round(min(max(target, ref * MIN_PRICE_K), ref * MAX_PRICE_K)))
