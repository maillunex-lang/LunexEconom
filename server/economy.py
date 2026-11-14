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
UPKEEP = "system:upkeep"      # sink for maintenance
BANK = "system:bank"            # lends and collects interest; may be negative (it creates the loan money)
RESIDENTS = "system:residents"  # receives wages (residents' spending is not modelled as a closed loop yet)
MAX_SETTLE_MONTHS = 600   # months processed per call when catching up

# ---- Tunable balance tables: change numbers here, nothing else depends on them ----
# output: units per full game month; upkeep: roubles per month.
# `inputs`: raw materials consumed per full month at full capacity (bought from the market when the owner's own
# stock is short). `capacity`: units of storage a warehouse adds (shared by all products of the owner).
PRODUCTION = {
    "farm":      {"product": "honey", "output": 100, "jobs": 4,  "upkeep": 2_000},
    "mine":      {"product": "oil",   "output": 40,  "jobs": 10, "upkeep": 15_000},
    "factory":   {"product": "goods", "output": 60,  "jobs": 20, "upkeep": 26_000, "inputs": {"oil": 10, "honey": 20}},
    "warehouse": {"product": None,    "output": 0,   "jobs": 2,  "upkeep": 2_000,  "capacity": 400},
}
# `upkeep` is maintenance only; wages are jobs * wage. At BASE_WAGE the total equals the old lump-sum upkeep
# (farm 8 000, mine 30 000, factory 56 000, warehouse 5 000), so building economics are unchanged at base wage.
#
# Residents and labour (one city for now):
#   labour force      = population * PARTICIPATION
#   staffing          = min(1, labour force / total jobs)  -> output of every producer is scaled by it
#   wage              = BASE_WAGE * clamp((jobs / labour force) ** WAGE_ELASTICITY, 1, WAGE_MAX)   (sticky downwards)
#   income ratio      = employed * wage / (labour force * BASE_WAGE)
#   consumer demand   = base_demand * season * (population / BASE_POPULATION) * (1 - INCOME_WEIGHT + INCOME_WEIGHT * min(income ratio, INCOME_CAP))
#   migration         = shortage of workers attracts people, unemployment drives them away; natural growth on top.
BASE_WAGE = 1_500
PARTICIPATION = 0.5
BASE_POPULATION = 200
MIN_POPULATION = 140
WAGE_ELASTICITY = 0.8
WAGE_MAX = 2.0
INCOME_WEIGHT = 0.25
INCOME_CAP = 1.5
NATURAL_GROWTH = 0.003
MIGRATION_IN = 0.03
MIGRATION_OUT = 0.005

# ---- Insolvency ----
# Costs a company cannot pay become arrears (wages, raw materials, maintenance; repaid in that order from later cash).
# An unpaid month cuts output to DISTRESS_OUTPUT (workers walk away). After BANKRUPT_AFTER_MISSED unpaid months in a row
# the company is liquidated: buildings leave the map, buildings/stock are sold for a share of their value, creditors
# are paid from the proceeds and the rest of the debt is written off. NPC owners get a new investor later.
BANKRUPT_AFTER_MISSED = 3
DISTRESS_OUTPUT = 0.5
LIQUIDATION_RATE = 0.4
SELL_RATE = 0.5                # voluntary sale of a building: better than a forced liquidation, still a loss
INVENTORY_LIQUIDATION_RATE = 0.5
NPC_RECAPITAL_MONTHS = 6

# ---- Bank: one revolving loan per company, secured by its buildings ----
# Limit = LOAN_LTV of the construction cost of the company's buildings (capped by LOAN_MAX). Interest is charged every game
# month after operating costs; interest that cannot be paid is added to the loan and counts as an unpaid month. A company in
# default (unpaid costs or arrears) gets no new credit. In bankruptcy the bank is the last creditor and loses the rest.
LOAN_INTEREST = 0.015
LOAN_LTV = 0.5
LOAN_MAX = 5_000_000
LOAN_MIN = 10_000
# A warehouse owner holds production back while last month's price was below reference * HOLD_BELOW
# and releases everything (stock included) once the price recovers.
HOLD_BELOW = 0.9
# Market: one world-wide market per product (regions/cities come later).
#   price = reference_price * (demand / supply) ** (1 / elasticity), clamped to [MIN_PRICE_K, MAX_PRICE_K] x reference.
#   demand = base_demand * season[calendar month] * demand scale (population and income, see above)
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
    "CREATE TABLE IF NOT EXISTS population(month_index BIGINT PRIMARY KEY, population BIGINT NOT NULL, labor_force BIGINT NOT NULL, jobs BIGINT NOT NULL, wage BIGINT NOT NULL, staffing_permille INTEGER NOT NULL, demand_permille INTEGER NOT NULL, next_population BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS company_status(owner TEXT PRIMARY KEY, missed INTEGER NOT NULL, wages_owed BIGINT NOT NULL, input_owed BIGINT NOT NULL, maint_owed BIGINT NOT NULL, bankruptcies INTEGER NOT NULL, last_bankruptcy_month BIGINT, written_off BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS loans(owner TEXT PRIMARY KEY, balance BIGINT NOT NULL, interest_paid BIGINT NOT NULL, taken_total BIGINT NOT NULL, repaid_total BIGINT NOT NULL)",
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
            "insolvency": {"bankrupt_after_missed": BANKRUPT_AFTER_MISSED, "loan": {"interest": LOAN_INTEREST, "ltv": LOAN_LTV, "max": LOAN_MAX, "min": LOAN_MIN}, "liquidation_rate": LIQUIDATION_RATE, "sell_rate": SELL_RATE, "distress_output": DISTRESS_OUTPUT},
            "labor": {"base_wage": BASE_WAGE, "participation": PARTICIPATION, "base_population": BASE_POPULATION},
            "production": {k: {"product_id": v["product"], "product": MARKET[v["product"]]["name"] if v["product"] else "",
                               "output": v["output"], "unit_price": MARKET[v["product"]]["reference_price"] if v["product"] else 0,
                               "upkeep": v["upkeep"], "jobs": v["jobs"], "inputs": dict(v.get("inputs", {})), "capacity": v.get("capacity", 0)}
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


def demand_for(product, month, scale=1.0):
    """Consumer demand of the population for a product in a game month; `scale` = population and income effect."""
    m = MARKET[product]
    return int(round(m["base_demand"] * m["season"][month % 12] * scale))


def wage_cost(kind, wage, staffing=1.0):
    return int(PRODUCTION[kind]["jobs"] * staffing * wage)


def monthly_cost(kind, wage, staffing=1.0):
    """Maintenance plus wages of a building at the given wage level."""
    return PRODUCTION[kind]["upkeep"] + wage_cost(kind, wage, staffing)


def price_for(product, supply, demand):
    """Clearing price for the given supply/demand (integer roubles)."""
    m = MARKET[product]
    ref = m["reference_price"]
    if supply <= 0:
        return int(round(ref * MAX_PRICE_K))
    target = ref * (max(demand, 0) / supply) ** (1.0 / m["elasticity"])
    return int(round(min(max(target, ref * MIN_PRICE_K), ref * MAX_PRICE_K)))
