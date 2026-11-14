"""NPC competitor companies.

NPCs are ordinary companies (`npc:<id>` owners) that act through the same public operations players use:
they build through `build()`, pay real money from a real wallet, and produce/sell/buy in the same world market
and the same monthly step. Decisions are deterministic (hash of owner and month), market-driven and slow:

  * once per completed game month an NPC rolls against its `pace`; on success it evaluates what a new building
    would earn at today's prices (`price_if_added`) and builds the best option whose payback is at most
    MAX_PAYBACK_MONTHS, so NPCs stop expanding when a market is saturated and leave room for players;
  * factories are only built when every raw material is actually offered on the market;
  * warehouses are added once an NPC has several producers.

The module only needs backend callables, so it works unchanged on SQLite and PostgreSQL.
"""
import hashlib
import threading
import uuid

import economy

SEED = 20261114
MAX_PAYBACK_MONTHS = 14        # NPCs accept slower payback than players expect (10), but not much slower
RESERVE = 100_000              # cash an NPC always keeps
ROAD_ESTIMATE_CELLS = 6        # access road assumed when estimating the cost of a new site
MAX_BUILDINGS = 15
MAX_CATCH_UP = 3               # months of decisions processed per tick after downtime
LOCATION_ATTEMPTS = 40
PLACEMENT_ERRORS = ("water", "road_overlap", "occupied", "no_road_access", "outside_world")

PERSONAS = [
    {"owner": "npc:ural-agro", "name": "Урал-Агро", "pace": 0.60,
     "focus": {"farm": 3.0, "warehouse": 1.0, "factory": 1.0, "mine": 0.5}},
    {"owner": "npc:bashneft-mini", "name": "БашНефть-Мини", "pace": 0.50,
     "focus": {"mine": 3.0, "warehouse": 1.0, "factory": 1.0, "farm": 0.5}},
    {"owner": "npc:ufa-industry", "name": "Уфа-Индастри", "pace": 0.40,
     "focus": {"factory": 3.0, "farm": 1.0, "mine": 1.0, "warehouse": 1.0}},
]
NAMES = {p["owner"]: p["name"] for p in PERSONAS}
_LOCK = threading.Lock()


def is_npc(owner):
    return str(owner).startswith("npc:")


def _rand(owner, month, salt):
    digest = hashlib.sha256(("%d|%s|%d|%s" % (SEED, owner, month, salt)).encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _profit(spec, quotes, wage=economy.BASE_WAGE, profit_tax=0.0, property_tax=0.0, cost=0):
    """Expected monthly profit after taxes of one more building of this kind, or None when it cannot operate."""
    profit = -(spec["upkeep"] + spec["jobs"] * wage)
    product = spec.get("product")
    if product:
        profit += spec["output"] * quotes[product]["price_if_added"]
    for raw, amount in spec.get("inputs", {}).items():
        if quotes[raw]["supply"] <= 0:
            return None                      # nobody sells this raw material: the factory would idle
        profit -= amount * quotes[raw]["price"]
    return profit - max(profit, 0) * profit_tax - cost * property_tax / 12


def choose_kind(persona, wallet, quotes, wage=economy.BASE_WAGE, tax_rates=None):
    """Best building kind to add now, or None."""
    holdings = wallet.get("holdings", {})
    total = sum(holdings.values())
    if total >= MAX_BUILDINGS:
        return None
    producers = sum(n for k, n in holdings.items() if economy.PRODUCTION.get(k, {}).get("product"))
    retail = quotes.get("_retail") or {}
    options = sorted(persona["focus"].items())
    if int(retail.get("unmet_units", 0)) > 0 and "shop" not in persona["focus"]:
        options.append(("shop", persona["focus"].get("shop", 1.0)))
    best = None
    seen = set()
    for kind, weight in options:
        if kind in seen or kind not in economy.PRODUCTION:
            continue
        seen.add(kind)
        cost = economy.BUILD_COST[kind] + economy.ROAD_CELL_COST * ROAD_ESTIMATE_CELLS
        if wallet["balance"] - cost < RESERVE:
            continue
        spec = economy.PRODUCTION[kind]
        if kind == "warehouse":
            if producers < 2 or holdings.get("warehouse", 0) >= (producers + 2) // 3:
                continue
            score = weight * 0.05            # only when nothing clearly profitable is available
        elif spec.get("role") == "retail":
            profit = _shop_profit(spec, retail, wage, (tax_rates or {}).get("profit", 0.0), (tax_rates or {}).get("property", 0.0), economy.BUILD_COST[kind])
            if profit is None or profit <= 0 or cost / profit > MAX_PAYBACK_MONTHS:
                continue
            score = weight / (cost / profit)
        else:
            profit = _profit(spec, quotes, wage, (tax_rates or {}).get("profit", 0.0), (tax_rates or {}).get("property", 0.0), economy.BUILD_COST[kind])
            if profit is None or profit <= 0 or cost / profit > MAX_PAYBACK_MONTHS:
                continue
            score = weight / (cost / profit)
        if best is None or score > best[0]:
            best = (score, kind)
    return best[1] if best else None


def _shop_profit(spec, retail, wage, profit_tax, property_tax, cost):
    """Expected margin of one shop that covers part of the unmet consumer demand, or None."""
    unmet = int(retail.get("unmet_units", 0))
    price = int(retail.get("unit_price") or 0)
    if unmet <= 0 or price <= 0:
        return None
    units = min(int(spec.get("floor", 0)), unmet)
    margin = int(units * price * economy.RETAIL_MARKUP / (1.0 + economy.RETAIL_MARKUP))
    profit = margin - (spec["upkeep"] + spec["jobs"] * wage)
    return profit - max(profit, 0) * profit_tax - cost * property_tax / 12


def _place(owner, month, kind, total, build_fn):
    radius = 12 + 3 * total
    for attempt in range(LOCATION_ATTEMPTS):
        h = _rand(owner, month, "loc%d" % attempt)
        x = h % (2 * radius + 1) - radius
        y = (h // 1000) % (2 * radius + 1) - radius
        request_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "npc/%s/%d/%d" % (owner, month, attempt)))
        status, result = build_fn(owner, {"kind": kind, "x": x, "y": y, "request_id": request_id})
        if status in (200, 201):
            return True
        if status == 402 or (status == 409 and result.get("error") not in PLACEMENT_ERRORS):
            return False
    return False


def act(persona, month, wallet_fn, market_fn, build_fn):
    """One monthly decision of one NPC. Returns the built kind or None."""
    owner = persona["owner"]
    if _rand(owner, month, "pace") % 1000 >= persona["pace"] * 1000:
        return None
    wallet = wallet_fn(owner)
    market = market_fn()
    t = market.get("taxes", {})
    products = dict(market.get("products") or {})
    if market.get("retail"):
        products["_retail"] = market["retail"]
    kind = choose_kind(persona, wallet, products, market.get("labor", {}).get("wage", economy.BASE_WAGE),
                       {"profit": t.get("profit_tax", 0.0), "property": t.get("property_tax", 0.0)})
    if kind is None:
        return None
    total = sum(wallet.get("holdings", {}).values())
    return kind if _place(owner, month, kind, total, build_fn) else None


def recapitalize(connect, ph, owner, now):
    """A new investor puts fresh capital into a bankrupt NPC."""
    with connect() as db:
        economy.post(db, ph, "recapital", "Новый инвестор", [(economy.player_account(owner), economy.START_CAPITAL), (economy.TREASURY, -economy.START_CAPITAL)], now)


def needs_investor(wallet, month):
    """True for a bankrupt NPC without buildings that has waited long enough."""
    last = wallet.get("company", {}).get("last_bankruptcy_month")
    return (last is not None and not wallet.get("holdings") and wallet["balance"] < economy.START_CAPITAL // 2
            and month - last >= economy.NPC_RECAPITAL_MONTHS)


CITY_MANAGER = "npc:city-manager"


def choose_social(view):
    """The administration (an NPC mayor) builds the least covered service when the budget can carry it for three months."""
    if not view["mayor"]["is_npc"] or not view.get("social"):
        return None
    coverage = view["social"]["coverage"]
    kind = min(sorted(coverage), key=lambda k: coverage[k])
    if coverage[kind] >= 0.95:
        return None
    reserve = 3 * (view.get("services_upkeep", 0) + economy.monthly_cost(kind, economy.BASE_WAGE))
    return kind if view["budget"] - economy.BUILD_COST[kind] >= reserve else None


def city_act(month, city_fn, build_fn):
    view = city_fn()
    kind = choose_social(view)
    if kind is None:
        return None
    return kind if _place(economy.CITY, month, kind, len(view.get("buildings", [])), build_fn) else None


def tick(connect, ph, clock_fn, market_fn, wallet_fn, build_fn, city_fn=None):
    """Let every NPC act for the months that have completed since it last acted. Cheap when nothing is pending."""
    if not _LOCK.acquire(blocking=False):
        return 0
    built = 0
    try:
        clk = clock_fn()
        month = clk["month_index"]
        with connect() as db:
            known = dict(db.execute("SELECT owner,acted_through FROM npc_state").fetchall())
            for index, persona in enumerate(PERSONAS):
                if persona["owner"] not in known:
                    # staggered start: NPCs begin acting during the first months, not all at once
                    known[persona["owner"]] = month - 2 - index
                    db.execute("INSERT INTO npc_state(owner,acted_through) VALUES(%s,%s)".replace("%s", ph), (persona["owner"], month - 2 - index))
        for persona in PERSONAS:
            acted = int(known[persona["owner"]])
            pending = month - 1 - acted
            if pending <= 0:
                continue
            if needs_investor(wallet_fn(persona["owner"]), month):
                recapitalize(connect, ph, persona["owner"], clk["server_time"])
            for k in range(min(pending, MAX_CATCH_UP)):
                if act(persona, acted + 1 + k, wallet_fn, market_fn, build_fn):
                    built += 1
            with connect() as db:
                db.execute("UPDATE npc_state SET acted_through=%s WHERE owner=%s".replace("%s", ph), (month - 1, persona["owner"]))
        if city_fn is not None:
            with connect() as db:
                row = db.execute("SELECT acted_through FROM npc_state WHERE owner=%s".replace("%s", ph), (CITY_MANAGER,)).fetchone()
                if row is None:
                    db.execute("INSERT INTO npc_state(owner,acted_through) VALUES(%s,%s)".replace("%s", ph), (CITY_MANAGER, month - 2))
            acted = int(row[0]) if row else month - 2
            pending = month - 1 - acted
            if pending > 0:
                for k in range(min(pending, MAX_CATCH_UP)):
                    if city_act(acted + 1 + k, city_fn, build_fn):
                        built += 1
                with connect() as db:
                    db.execute("UPDATE npc_state SET acted_through=%s WHERE owner=%s".replace("%s", ph), (month - 1, CITY_MANAGER))
        return built
    finally:
        _LOCK.release()
