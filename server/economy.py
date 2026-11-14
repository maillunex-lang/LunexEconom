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
BUILD_COST = {"farm": 120_000, "mine": 300_000, "factory": 450_000, "warehouse": 80_000,
              "shop": 160_000,
              "school": 400_000, "hospital": 800_000, "park": 150_000}   # social buildings are paid from the city budget
ROAD_CELL_COST = 5_000
TREASURY = "system:treasury"
CONSTRUCTION = "system:construction"
MARKET_ACCOUNT = "system:market"      # buys all production at the clearing price
UPKEEP = "system:upkeep"      # sink for maintenance
BANK = "system:bank"            # lends and collects interest; may be negative (it creates the loan money)
RESIDENTS = "system:residents"  # receives wages and spends them on consumer goods (money returns to system:market)
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
    # A shop does not produce. It sells consumer goods (MARKET consumer=True) to residents. `floor` is units per month.
    "shop":      {"product": None,    "output": 0,   "jobs": 5,  "upkeep": 3_000,  "floor": 100, "role": "retail"},
    # Social buildings belong to the city (built by the mayor from the budget); `serves` = residents covered per building.
    "school":    {"product": None,    "output": 0,   "jobs": 6,  "upkeep": 3_000,  "serves": 120},
    "hospital":  {"product": None,    "output": 0,   "jobs": 8,  "upkeep": 5_000,  "serves": 200},
    "park":      {"product": None,    "output": 0,   "jobs": 2,  "upkeep": 1_000,  "serves": 250},
}
SOCIAL_KINDS = ("school", "hospital", "park")
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

# ---- Taxes (rates researched for Russia / Republic of Bashkortostan, see docs/TAXES.md) ----
# Game defaults chosen by the owner: profit tax 13 %, VAT by product category up to 22 %, property tax at the Bashkortostan
# general rate 2.2 % a year. All tax revenue goes to the city budget (account of the pseudo-owner CITY).
# VAT is federal law (not regulated by the mayor); the mayor may change profit and property tax inside the legal limits.
TAXES_ENABLED = True
CITY = "city"                          # pseudo-owner whose wallet is the city budget (no start capital, never bankrupt)
VAT_STANDARD = 0.22                    # general rate from 2026-01-01 (Federal Law 425-FZ)
VAT_RATES = {"honey": 0.10,            # food: reduced rate 10 % (inclusion of honey in the list is not verified, rate is a setting)
             "oil": 0.22,              # raw material: general rate
             "goods": 0.22}            # manufactured goods: general rate
DEFAULT_PROFIT_TAX = 0.13
PROFIT_TAX_LIMITS = (0.05, 0.25)       # real total profit tax is 25 % (8 % federal + 17 % regional)
DEFAULT_PROPERTY_TAX = 0.022           # per year of the book value of buildings; Bashkortostan general rate (cap 2.2 % by Tax Code art. 380)
PROPERTY_TAX_LIMITS = (0.0, 0.022)

# ---- City government and social services ----
# quality of life = average coverage of schools, hospitals and parks (0..1); an underfunded city (budget arrears) works at half.
# It raises output (educated, healthy workers), natural growth and immigration, and reduces emigration.
SOCIAL_PRODUCTIVITY = 0.10
SOCIAL_GROWTH = 0.002
MAYOR_SALARY = 40_000          # per game month from the budget, only for a human mayor
MAYOR_BONUS_SHARE = 0.02       # performance bonus: share of the taxes the city collected in the month, paid from the budget
TERM_BONUS = ((0.75, 600_000), (0.60, 300_000))   # end-of-term reward from the Republic (treasury, not the budget) by average rating
# Mayor rating (0..1), smoothed monthly: 70 % residents' approval (quality of life, employment, healthy budget) +
# 30 % business approval (tax burden). A human mayor below DISMISS_BELOW for DISMISS_AFTER months in a row is dismissed
# (the administration governs until the next election). Nobody may govern more than MAX_CONSECUTIVE_TERMS terms in a row.
RATING_RESIDENTS_WEIGHT = 0.7
RATING_SMOOTHING = 0.2
DISMISS_BELOW = 0.15
DISMISS_AFTER = 3
MAX_CONSECUTIVE_TERMS = 2
ROAD_MAINTENANCE = 30          # per built road cell per month from the budget
ELECTION_PERIOD = 12           # game months between elections (the length of a mayor's term)
ELECTION_REGISTRATION_MONTHS = 2   # candidates register in the two months before voting starts
ELECTION_VOTING_MONTHS = 2         # voting lasts two months; the result is counted when the last of them completes
ELECTION_FEE = 50_000              # candidacy fee paid into the city budget
VOTE_WEIGHT_BASE = 10              # a player's vote weight = base + per_job * jobs of the player's company
VOTE_WEIGHT_PER_JOB = 5
RESERVED_OWNERS = ("city",)    # nobody may register under these names

# ---- Bank: one revolving loan per company, secured by its buildings ----
# Limit = LOAN_LTV of the construction cost of the company's buildings (capped by LOAN_MAX). Interest is charged every game
# month after operating costs; interest that cannot be paid is added to the loan and counts as an unpaid month. A company in
# default (unpaid costs or arrears) gets no new credit. In bankruptcy the bank is the last creditor and loses the rest.
LOAN_INTEREST = 0.015
LOAN_LTV = 0.5
LOAN_MAX = 5_000_000
LOAN_MIN = 10_000
# A new company borrows only LOAN_NEW_LTV of its buildings. The rest of the way to LOAN_LTV opens with age
# (LOAN_RAMP_MONTHS of operation) and with confirmed revenue (average of the last LOAN_REVENUE_MONTHS at least
# LOAN_REVENUE_PROOF). Both are required: time alone or one lucky month alone does not unlock the full limit.
LOAN_NEW_LTV = 0.12
LOAN_RAMP_MONTHS = 12
LOAN_REVENUE_MONTHS = 3
LOAN_REVENUE_PROOF = 20_000
# A warehouse owner holds production back while the recent average price is below reference * HOLD_BELOW. The held share grows
# with the depth of the fall (the full output is held only at HOLD_BELOW * (1 - HOLD_DEPTH)) and the stock is released gradually
# (RELEASE_SHARE of it per month, all of it at once while the price is above the reference). Fractions instead of an all-or-nothing
# rule keep all warehouses from switching in the same month (supply 0 -> price at the ceiling -> everything dumped -> price at the floor).
HOLD_BELOW = 0.9
HOLD_DEPTH = 0.5
HOLD_SMOOTH_MONTHS = 3
RELEASE_SHARE = 0.34
# Residents spend the wages they earned on consumer goods: money flows system:residents -> system:market (closed money circle).
RESIDENT_SPEND_TO_MARKET = True
# Owners spend a share of positive after-tax operating profit on their own life. The money returns to system:market,
# so producer profit is not paid out of thin air. Cash above OWNER_SPEND_RESERVE_MONTHS of wages, maintenance and
# raw materials is what may be spent; the city budget does not consume. Share 0.90 and a 3-month reserve: a farm
# that is actually earning stays in the black (about 10% of after-tax profit plus the reserve), while the stock of
# unspent owner profit stops compounding. See docs/OWNER_SPENDING.md.
OWNER_SPEND_ENABLED = True
OWNER_SPEND_SHARE = 0.90
OWNER_SPEND_RESERVE_MONTHS = 3
# Retail: a shop sells consumer goods to residents at a markup. With no shops the wage loop is unchanged.
# See docs/RETAIL.md.
RETAIL_ENABLED = True
RETAIL_MARKUP = 0.30
# Market: one world-wide market per product (regions/cities come later).
#   price = reference_price * (demand / supply) ** (1 / elasticity), clamped to [MIN_PRICE_K, MAX_PRICE_K] x reference.
#   demand = base_demand * season[calendar month] * demand scale (population and income, see above)
# base_demand = 2 buildings' output: the world absorbs two buildings of a kind at the reference price;
# a lone first building enjoys a premium, a crowded market pushes prices (and profit) down.
MARKET = {
    "honey": {"name": "Мёд",    "reference_price": 200,  "base_demand": 200, "elasticity": 1.5, "consumer": True,
              "season": [1.15, 1.10, 1.00, 0.95, 0.90, 0.90, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15]},
    "oil":   {"name": "Нефть",  "reference_price": 1500, "base_demand": 80,  "elasticity": 1.5, "consumer": False,
              "season": [1.15, 1.10, 1.05, 0.95, 0.90, 0.85, 0.85, 0.90, 0.95, 1.05, 1.10, 1.15]},
    "goods": {"name": "Товары", "reference_price": 2000, "base_demand": 120, "elasticity": 1.5, "consumer": True,
              "season": [0.95, 0.90, 0.95, 1.00, 1.00, 1.00, 1.00, 1.05, 1.05, 1.05, 1.10, 1.25]},
}
MIN_PRICE_K = 0.25
MAX_PRICE_K = 2.5

# ---- Direct contracts between players (see docs/CONTRACTS.md) ----
# Price is checked against the reference (base) price, not the live quote, so the bound does not move under the player.
CONTRACT_PRODUCTS = ("honey", "oil", "goods")
CONTRACT_PRICE_MIN_K = 0.50
CONTRACT_PRICE_MAX_K = 2.00
CONTRACT_QTY_MIN = 1
CONTRACT_QTY_MAX = 10_000
CONTRACT_TERM_MIN = 1
CONTRACT_TERM_MAX = 24
CONTRACT_MAX_ACTIVE = 6
CONTRACT_MAX_OPEN = 6

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
    "CREATE TABLE IF NOT EXISTS city_policy(id INTEGER PRIMARY KEY, profit_tax_permille INTEGER NOT NULL, property_tax_permille INTEGER NOT NULL, social_share_permille INTEGER NOT NULL, changed_month BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS company_tax_state(owner TEXT PRIMARY KEY, tax_owed BIGINT NOT NULL, vat_credit BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS company_taxes(owner TEXT NOT NULL, month_index BIGINT NOT NULL, vat BIGINT NOT NULL, profit_tax BIGINT NOT NULL, property_tax BIGINT NOT NULL, paid BIGINT NOT NULL, PRIMARY KEY(owner, month_index))",
    "CREATE TABLE IF NOT EXISTS city_state(id INTEGER PRIMARY KEY, mayor TEXT NOT NULL, mayor_name TEXT NOT NULL, since_month BIGINT NOT NULL, term_end_month BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS mayor_rating(month_index BIGINT PRIMARY KEY, mayor TEXT NOT NULL, residents_permille INTEGER NOT NULL, business_permille INTEGER NOT NULL, total_permille INTEGER NOT NULL, low_streak INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS mayor_terms(mayor TEXT NOT NULL, name TEXT NOT NULL, from_month BIGINT NOT NULL, to_month BIGINT, reason TEXT, avg_rating_permille INTEGER, bonus BIGINT NOT NULL DEFAULT 0, PRIMARY KEY(from_month, mayor))",
    "CREATE TABLE IF NOT EXISTS election_candidates(election BIGINT NOT NULL, candidate TEXT NOT NULL, name TEXT NOT NULL, profit_permille INTEGER NOT NULL, property_permille INTEGER NOT NULL, social_permille INTEGER NOT NULL, slogan TEXT NOT NULL, PRIMARY KEY(election, candidate))",
    "CREATE TABLE IF NOT EXISTS election_votes(election BIGINT NOT NULL, voter TEXT NOT NULL, candidate TEXT NOT NULL, PRIMARY KEY(election, voter))",
    "CREATE TABLE IF NOT EXISTS election_results(election BIGINT PRIMARY KEY, winner TEXT NOT NULL, winner_name TEXT NOT NULL, tally TEXT NOT NULL, month_index BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS npc_state(owner TEXT PRIMARY KEY, acted_through BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS company_state(owner TEXT PRIMARY KEY, settled_through BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS monthly_reports(owner TEXT NOT NULL, month_index BIGINT NOT NULL, revenue BIGINT NOT NULL, upkeep BIGINT NOT NULL, profit BIGINT NOT NULL, buildings INTEGER NOT NULL, PRIMARY KEY(owner, month_index))",
    "CREATE TABLE IF NOT EXISTS ledger_entries(tx_id TEXT NOT NULL REFERENCES ledger_tx(id), account TEXT NOT NULL, amount BIGINT NOT NULL, PRIMARY KEY(tx_id, account))",
    "CREATE TABLE IF NOT EXISTS trade_offers(id TEXT PRIMARY KEY, supplier TEXT NOT NULL, product TEXT NOT NULL, qty BIGINT NOT NULL, price BIGINT NOT NULL, term_months INTEGER NOT NULL, penalty BIGINT NOT NULL, status TEXT NOT NULL, created_month BIGINT NOT NULL, created BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS trade_contracts(id TEXT PRIMARY KEY, offer_id TEXT NOT NULL, supplier TEXT NOT NULL, buyer TEXT NOT NULL, product TEXT NOT NULL, qty BIGINT NOT NULL, price BIGINT NOT NULL, penalty BIGINT NOT NULL, start_month BIGINT NOT NULL, end_month BIGINT NOT NULL, status TEXT NOT NULL, closed_reason TEXT NOT NULL DEFAULT '', created BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS trade_deliveries(contract_id TEXT NOT NULL, month_index BIGINT NOT NULL, delivered BIGINT NOT NULL, shortfall BIGINT NOT NULL, paid BIGINT NOT NULL, penalty_paid BIGINT NOT NULL, PRIMARY KEY(contract_id, month_index))",
    "CREATE TABLE IF NOT EXISTS trade_debts(debtor TEXT NOT NULL, creditor TEXT NOT NULL, amount BIGINT NOT NULL, PRIMARY KEY(debtor, creditor))",
    "CREATE TABLE IF NOT EXISTS eco_owner_spend(owner TEXT NOT NULL, month_index BIGINT NOT NULL, amount BIGINT NOT NULL, PRIMARY KEY(owner, month_index))",
)


def player_account(owner):
    return "player:" + owner


def build_cost(kind, road_cells):
    return BUILD_COST[kind] + ROAD_CELL_COST * road_cells


def terms():
    return {"currency": CURRENCY, "start_capital": START_CAPITAL,
            "building_costs": dict(BUILD_COST), "road_cell_cost": ROAD_CELL_COST,
            "hold_below": HOLD_BELOW, "hold_depth": HOLD_DEPTH, "release_share": RELEASE_SHARE,
            "contracts": {"products": list(CONTRACT_PRODUCTS), "price_min_k": CONTRACT_PRICE_MIN_K, "price_max_k": CONTRACT_PRICE_MAX_K,
                          "qty": [CONTRACT_QTY_MIN, CONTRACT_QTY_MAX], "term_months": [CONTRACT_TERM_MIN, CONTRACT_TERM_MAX],
                          "max_active": CONTRACT_MAX_ACTIVE, "max_open": CONTRACT_MAX_OPEN},
            "city": {"social_cost": {k: BUILD_COST[k] for k in SOCIAL_KINDS}, "serves": {k: PRODUCTION[k]["serves"] for k in SOCIAL_KINDS},
                     "mayor_salary": MAYOR_SALARY, "election_period": ELECTION_PERIOD, "election_fee": ELECTION_FEE,
                     "bonus_share": MAYOR_BONUS_SHARE, "term_bonus": [[t, b] for t, b in TERM_BONUS], "max_terms": MAX_CONSECUTIVE_TERMS,
                     "dismiss_below": DISMISS_BELOW, "dismiss_after": DISMISS_AFTER, "productivity": SOCIAL_PRODUCTIVITY},
            "insolvency": {"bankrupt_after_missed": BANKRUPT_AFTER_MISSED, "loan": {"interest": LOAN_INTEREST, "ltv": LOAN_LTV, "new_ltv": LOAN_NEW_LTV, "ramp_months": LOAN_RAMP_MONTHS, "revenue_proof": LOAN_REVENUE_PROOF, "max": LOAN_MAX, "min": LOAN_MIN}, "liquidation_rate": LIQUIDATION_RATE, "sell_rate": SELL_RATE, "distress_output": DISTRESS_OUTPUT},
            "labor": {"base_wage": BASE_WAGE, "participation": PARTICIPATION, "base_population": BASE_POPULATION},
            "production": {k: {"product_id": v["product"], "product": MARKET[v["product"]]["name"] if v["product"] else "",
                               "output": v["output"], "unit_price": MARKET[v["product"]]["reference_price"] if v["product"] else 0,
                               "upkeep": v["upkeep"], "jobs": v["jobs"], "inputs": dict(v.get("inputs", {})), "capacity": v.get("capacity", 0),
                               "floor": v.get("floor", 0), "role": v.get("role", ""),
                               "retail_hint": 18_000 if v.get("role") == "retail" else 0}
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
    if cur.rowcount == 1 and owner != CITY:
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
