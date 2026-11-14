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
MARKET_ACCOUNT = "system:market"      # buys all production at the clearing price
UPKEEP = "system:upkeep"      # sink for salaries and maintenance
MAX_SETTLE_MONTHS = 600

# ---- Tunable balance tables: change numbers here, nothing else depends on them ----
# output: units per full game month; upkeep: roubles per month.
PRODUCTION = {
    "farm":    {"product": "honey", "output": 100, "upkeep": 8_000},
    "mine":    {"product": "oil",   "output": 40,  "upkeep": 30_000},
    "factory": {"product": "goods", "output": 60,  "upkeep": 75_000},
}
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
            "production": {k: {"product_id": v["product"], "product": MARKET[v["product"]]["name"], "output": v["output"],
                               "unit_price": MARKET[v["product"]]["reference_price"], "upkeep": v["upkeep"]}
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


def _factor(start_month, permille, month):
    return 1000 - permille if start_month == month else 1000


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


def _all_ops(db, ph):
    return db.execute("SELECT kind,start_month,start_permille FROM building_ops").fetchall()


def supply_for(ops, product, month, full=False):
    """Units of `product` produced in `month` by all buildings in the world."""
    total = 0
    for kind, start_month, permille in ops:
        spec = PRODUCTION.get(kind)
        if spec is None or spec["product"] != product or start_month > month:
            continue
        total += spec["output"] * (1000 if full else _factor(start_month, permille, month)) // 1000
    return total


def month_price(db, ph, product, month):
    """Price of a completed month. Computed once from that month's supply and stored, so every
    player settles at the same price regardless of when they log in."""
    row = db.execute("SELECT price FROM market_prices WHERE product=%s AND month_index=%s".replace("%s", ph), (product, month)).fetchone()
    if row is None:
        supply = supply_for(_all_ops(db, ph), product, month)
        demand = demand_for(product, month)
        db.execute("INSERT INTO market_prices(product,month_index,price,supply,demand) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(product,month_index) DO NOTHING".replace("%s", ph),
                   (product, month, price_for(product, supply, demand), supply, demand))
        row = db.execute("SELECT price FROM market_prices WHERE product=%s AND month_index=%s".replace("%s", ph), (product, month)).fetchone()
    return int(row[0])


def quote(db, ph, clk):
    """Current (provisional) market state per product, including the price if one more building were added."""
    month = clk["month_index"]
    ops = _all_ops(db, ph)
    out = {}
    for kind, spec in PRODUCTION.items():
        product = spec["product"]
        supply = supply_for(ops, product, month, full=True)
        demand = demand_for(product, month)
        previous = db.execute("SELECT price FROM market_prices WHERE product=%s AND month_index=%s".replace("%s", ph), (product, month - 1)).fetchone()
        m = MARKET[product]
        out[product] = {"kind": kind, "name": m["name"], "reference_price": m["reference_price"], "supply": supply, "demand": demand,
                        "price": price_for(product, supply, demand), "price_if_added": price_for(product, supply + spec["output"], demand),
                        "previous_price": int(previous[0]) if previous else None}
    return out


def register_building(db, ph, owner, object_id, kind, clk):
    """Start production for a new building. `clk` is clock.state(); the first month is prorated."""
    month = clk["month_index"]
    elapsed = clk["month_seconds"] - clk["seconds_to_next_month"]
    permille = min(999, max(0, elapsed * 1000 // clk["month_seconds"]))
    if db.execute("SELECT 1 FROM company_state WHERE owner=%s".replace("%s", ph), (owner,)).fetchone() is None:
        db.execute("INSERT INTO company_state(owner,settled_through) VALUES(%s,%s)".replace("%s", ph), (owner, month - 1))
    db.execute("INSERT INTO building_ops(object_id,owner,kind,start_month,start_permille) VALUES(%s,%s,%s,%s,%s)".replace("%s", ph),
               (object_id, owner, kind, month, permille))


def settle(db, ph, owner, clk, now):
    """Pay every completed game month that has not been settled yet (idempotent, lazy catch-up)."""
    # Buildings created before production existed start operating from now.
    for object_id, kind in db.execute("SELECT id,kind FROM buildings WHERE owner=%s AND id NOT IN (SELECT object_id FROM building_ops)".replace("%s", ph), (owner,)).fetchall():
        register_building(db, ph, owner, object_id, kind, clk)
    row = db.execute("SELECT settled_through FROM company_state WHERE owner=%s".replace("%s", ph), (owner,)).fetchone()
    if row is None:
        return 0
    first = int(row[0]) + 1
    last = min(clk["month_index"] - 1, first + MAX_SETTLE_MONTHS - 1)
    if last < first:
        return 0
    ops = db.execute("SELECT kind,start_month,start_permille FROM building_ops WHERE owner=%s".replace("%s", ph), (owner,)).fetchall()
    account = player_account(owner)
    for month in range(first, last + 1):
        revenue = upkeep = count = 0
        for kind, start_month, permille in ops:
            spec = PRODUCTION.get(kind)
            if spec is None or start_month > month:
                continue
            factor = _factor(start_month, permille, month)
            revenue += spec["output"] * factor * month_price(db, ph, spec["product"], month) // 1000
            upkeep += spec["upkeep"] * factor // 1000
            count += 1
        if count:
            available = (balance(db, ph, owner) or 0) + revenue
            paid_upkeep = min(upkeep, available)   # unpaid upkeep is not turned into debt (bankruptcy rules come later)
            profit = revenue - paid_upkeep
            post(db, ph, "monthly", "Итоги месяца: доход %d, расходы %d" % (revenue, paid_upkeep),
                 [(account, profit), (MARKET_ACCOUNT, -revenue), (UPKEEP, paid_upkeep)], now)
            db.execute("INSERT INTO monthly_reports(owner,month_index,revenue,upkeep,profit,buildings) VALUES(%s,%s,%s,%s,%s,%s)".replace("%s", ph),
                       (owner, month, revenue, paid_upkeep, profit, count))
    db.execute("UPDATE company_state SET settled_through=%s WHERE owner=%s".replace("%s", ph), (last, owner))
    return last - first + 1


def forecast(db, ph, owner, quotes):
    """Expected monthly result at current market prices."""
    revenue = upkeep = count = 0
    for (kind,) in db.execute("SELECT kind FROM building_ops WHERE owner=%s".replace("%s", ph), (owner,)).fetchall():
        spec = PRODUCTION.get(kind)
        if spec:
            revenue += spec["output"] * quotes[spec["product"]]["price"]
            upkeep += spec["upkeep"]
            count += 1
    return {"revenue": revenue, "upkeep": upkeep, "profit": revenue - upkeep, "buildings": count}


def reports(db, ph, owner, limit=6):
    rows = db.execute("SELECT month_index,revenue,upkeep,profit,buildings FROM monthly_reports WHERE owner=%s ORDER BY month_index DESC LIMIT %s".replace("%s", ph),
                      (owner, limit)).fetchall()
    return [{"month_index": m, "revenue": r, "upkeep": u, "profit": p, "buildings": b} for m, r, u, p, b in rows]


def wallet(db, ph, owner, clk, now):
    settle(db, ph, owner, clk, now)
    bal = ensure_wallet(db, ph, owner, now)
    quotes = quote(db, ph, clk)
    return {"ok": True, "balance": bal, "currency": CURRENCY, "transactions": history(db, ph, owner),
            "forecast": forecast(db, ph, owner, quotes), "reports": reports(db, ph, owner), "month_index": clk["month_index"], "market": quotes}
