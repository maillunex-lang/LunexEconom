"""Production chains, warehouses and the world-wide monthly market step.

One global step per completed game month processes *all* companies in a fixed order, so prices are
identical for everybody. Products are cleared in dependency order (raw materials, then goods):

  1. every company produces; factories first use their own stock/production as inputs;
  2. warehouse owners may hold production back while the last known price is low;
  3. offers of a product are summed; demand = population + factories' missing inputs;
  4. clearing price = economy.price_for(product, offers, demand); factories buy their missing inputs at it
     (scarcity rations them proportionally), producers sell their offers at it;
  5. factory output is limited by the scarcest input;
  6. each company settles in one balanced ledger transaction (revenue - input purchases - upkeep).

Shared by SQLite and PostgreSQL; all functions run inside the caller's transaction (`ph` = SQL placeholder).
"""
import economy


def _q(sql, ph):
    return sql.replace("%s", ph)


def _spec(kind):
    return economy.PRODUCTION.get(kind)


def _factor(start_month, permille, month):
    """Share of the month a building works: the construction month is prorated."""
    return 1000 - permille if start_month == month else 1000


def product_order():
    """Products in clearing order: those not made from inputs come first."""
    products = {s["product"] for s in economy.PRODUCTION.values() if s.get("product")}
    derived = {s["product"] for s in economy.PRODUCTION.values() if s.get("product") and s.get("inputs")}
    return sorted(products - derived) + sorted(derived)


def input_products():
    return {p for s in economy.PRODUCTION.values() for p in s.get("inputs", {})}


def register_building(db, ph, owner, object_id, kind, clk):
    """Start operating a new building; the construction month is prorated."""
    month = clk["month_index"]
    elapsed = clk["month_seconds"] - clk["seconds_to_next_month"]
    permille = min(999, max(0, elapsed * 1000 // clk["month_seconds"]))
    db.execute(_q("INSERT INTO building_ops(object_id,owner,kind,start_month,start_permille) VALUES(%s,%s,%s,%s,%s)", ph),
               (object_id, owner, kind, month, permille))


def _price_row(db, ph, product, month):
    row = db.execute(_q("SELECT price FROM market_prices WHERE product=%s AND month_index=%s", ph), (product, month)).fetchone()
    return int(row[0]) if row else None


def _save_inventory(db, ph, owner, stock):
    for product, qty in sorted(stock.items()):
        db.execute(_q("INSERT INTO inventory(owner,product,qty) VALUES(%s,%s,%s) ON CONFLICT(owner,product) DO UPDATE SET qty=excluded.qty", ph),
                   (owner, product, qty))


def step_month(db, ph, month, now):
    """Run the market step for one completed month."""
    ops = db.execute(_q("SELECT owner,kind,start_month,start_permille FROM building_ops WHERE start_month<=%s", ph), (month,)).fetchall()
    companies = {}
    for owner, kind, start_month, permille in sorted(ops):
        spec = _spec(kind)
        if spec is None:
            continue
        c = companies.setdefault(owner, {"buildings": [], "upkeep": 0, "capacity": 0, "stock": {}, "needs": {}, "got": {},
                                         "need_ext": {}, "revenue": 0, "input_cost": 0})
        factor = _factor(start_month, permille, month)
        c["buildings"].append((kind, factor))
        c["upkeep"] += spec["upkeep"] * factor // 1000
        c["capacity"] += spec.get("capacity", 0)
        for product, amount in spec.get("inputs", {}).items():
            c["needs"][product] = c["needs"].get(product, 0) + amount * factor // 1000
    for owner, product, qty in db.execute("SELECT owner,product,qty FROM inventory").fetchall():
        if owner in companies:
            companies[owner]["stock"][product] = int(qty)

    consumed = input_products()
    prices = {}
    for product in product_order():
        ref = economy.MARKET[product]["reference_price"]
        previous = _price_row(db, ph, product, month - 1)
        hold = previous is not None and previous < ref * economy.HOLD_BELOW
        offers = {}
        for owner, c in companies.items():
            produced = 0
            for kind, factor in c["buildings"]:
                spec = _spec(kind)
                if spec["product"] != product:
                    continue
                out = spec["output"] * factor // 1000
                if spec.get("inputs"):
                    out = int(out * _input_fraction(c))
                produced += out
            stock = c["stock"].get(product, 0)
            need = c["needs"].get(product, 0)
            if product in consumed and need:
                internal = min(need, produced + stock)          # own supply first, no market purchase
                from_prod = min(internal, produced)
                produced -= from_prod
                stock -= internal - from_prod
                c["got"][product] = internal
                c["need_ext"][product] = need - internal
            if c["capacity"] > 0 and hold:
                free = max(0, c["capacity"] - sum(v for k, v in c["stock"].items() if k != product) - stock)
                held = min(produced, free)
                stock += held
                offers[owner] = produced - held
            else:
                offers[owner] = produced + stock
                stock = 0
            c["stock"][product] = stock
        supply = sum(offers.values())
        demand_ext = sum(c["need_ext"].get(product, 0) for c in companies.values())
        demand = economy.demand_for(product, month) + demand_ext
        price = economy.price_for(product, supply, demand)
        prices[product] = price
        fill = 1.0 if demand <= 0 else min(1.0, supply / demand)
        for owner, c in companies.items():
            c["revenue"] += offers[owner] * price
            ext = c["need_ext"].get(product, 0)
            if ext:
                bought = int(ext * fill)
                c["got"][product] = c["got"].get(product, 0) + bought
                c["input_cost"] += bought * price
        db.execute(_q("INSERT INTO market_prices(product,month_index,price,supply,demand) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(product,month_index) DO NOTHING", ph),
                   (product, month, price, supply, demand))

    for owner, c in sorted(companies.items()):
        available = (economy.balance(db, ph, owner) or 0) + c["revenue"]
        paid_input = min(c["input_cost"], max(available, 0))
        paid_upkeep = min(c["upkeep"], max(available - paid_input, 0))   # no debt: unpaid costs are forgiven (bankruptcy rules later)
        profit = c["revenue"] - paid_input - paid_upkeep
        if c["revenue"] or paid_input or paid_upkeep:
            economy.post(db, ph, "monthly", "Итоги месяца: доход %d, сырьё %d, содержание %d" % (c["revenue"], paid_input, paid_upkeep),
                         [(economy.player_account(owner), profit), (economy.MARKET_ACCOUNT, -c["revenue"] + paid_input), (economy.UPKEEP, paid_upkeep)], now)
        db.execute(_q("INSERT INTO company_reports(owner,month_index,revenue,input_cost,upkeep,profit,buildings) VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(owner,month_index) DO NOTHING", ph),
                   (owner, month, c["revenue"], paid_input, paid_upkeep, profit, len(c["buildings"])))
        _save_inventory(db, ph, owner, c["stock"])


def _input_fraction(c):
    """Share of full capacity a company's factories can run at, limited by the scarcest input."""
    fraction = 1.0
    for product, need in c["needs"].items():
        if need > 0:
            fraction = min(fraction, c["got"].get(product, 0) / need)
    return fraction


def advance(db, ph, clk, now):
    """Process all completed, not yet processed months for the whole world (idempotent)."""
    for object_id, owner, kind in db.execute("SELECT id,owner,kind FROM buildings WHERE id NOT IN (SELECT object_id FROM building_ops)").fetchall():
        register_building(db, ph, owner, object_id, kind, clk)     # buildings from before production existed start now
    row = db.execute("SELECT processed_through FROM world_state WHERE id=1").fetchone()
    if row is None:
        legacy = db.execute("SELECT MAX(settled_through) FROM company_state").fetchone()[0]
        start = max(clk["month_index"] - 1, int(legacy)) if legacy is not None else clk["month_index"] - 1
        db.execute(_q("INSERT INTO world_state(id,processed_through) VALUES(1,%s)", ph), (start,))
        return 0
    done = int(row[0])
    last = min(clk["month_index"] - 1, done + economy.MAX_SETTLE_MONTHS)
    for month in range(done + 1, last + 1):
        step_month(db, ph, month, now)
    if last > done:
        db.execute(_q("UPDATE world_state SET processed_through=%s WHERE id=1", ph), (last,))
    return max(0, last - done)


def _ops(db, ph):
    return db.execute("SELECT owner,kind,start_month,start_permille FROM building_ops").fetchall()


def quote(db, ph, clk):
    """Provisional market state for the running month, plus the price if one more producer were added."""
    month = clk["month_index"]
    ops = _ops(db, ph)
    out = {}
    for product in product_order():
        producing_kind = next(k for k, s in economy.PRODUCTION.items() if s.get("product") == product)
        output = economy.PRODUCTION[producing_kind]["output"]
        supply = sum(economy.PRODUCTION[k]["output"] for _, k, sm, _p in ops if k in economy.PRODUCTION and economy.PRODUCTION[k].get("product") == product and sm <= month)
        need = sum(n for _, k, sm, _p in ops if sm <= month for p, n in economy.PRODUCTION.get(k, {}).get("inputs", {}).items() if p == product)
        demand = economy.demand_for(product, month) + need
        m = economy.MARKET[product]
        out[product] = {"kind": producing_kind, "name": m["name"], "reference_price": m["reference_price"], "supply": supply, "demand": demand,
                        "price": economy.price_for(product, supply, demand), "price_if_added": economy.price_for(product, supply + output, demand),
                        "previous_price": _price_row(db, ph, product, month - 1)}
    return out


def forecast(db, ph, owner, quotes):
    """Expected monthly result at current prices (all production sold, all inputs bought)."""
    revenue = inputs = upkeep = count = 0
    for kind, in db.execute(_q("SELECT kind FROM building_ops WHERE owner=%s", ph), (owner,)).fetchall():
        spec = _spec(kind)
        if not spec:
            continue
        if spec.get("product"):
            revenue += spec["output"] * quotes[spec["product"]]["price"]
        for product, amount in spec.get("inputs", {}).items():
            inputs += amount * quotes[product]["price"]
        upkeep += spec["upkeep"]
        count += 1
    return {"revenue": revenue, "input_cost": inputs, "upkeep": upkeep, "profit": revenue - inputs - upkeep, "buildings": count}


def inventory_view(db, ph, owner):
    rows = db.execute(_q("SELECT product,qty FROM inventory WHERE owner=%s ORDER BY product", ph), (owner,)).fetchall()
    capacity = sum(_spec(k)["capacity"] for k, in db.execute(_q("SELECT kind FROM building_ops WHERE owner=%s", ph), (owner,)).fetchall()
                   if _spec(k) and _spec(k).get("capacity"))
    items = [{"product": p, "name": economy.MARKET[p]["name"], "qty": int(q)} for p, q in rows if p in economy.MARKET and q > 0]
    return {"items": items, "used": sum(i["qty"] for i in items), "capacity": capacity}


def reports(db, ph, owner, limit=6):
    rows = db.execute(_q("SELECT month_index,revenue,input_cost,upkeep,profit,buildings FROM company_reports WHERE owner=%s ORDER BY month_index DESC LIMIT %s", ph),
                      (owner, limit)).fetchall()
    return [{"month_index": m, "revenue": r, "input_cost": i, "upkeep": u, "profit": p, "buildings": b} for m, r, i, u, p, b in rows]


def holdings(db, ph, owner):
    """Number of buildings per kind."""
    out = {}
    for kind, in db.execute(_q("SELECT kind FROM building_ops WHERE owner=%s", ph), (owner,)).fetchall():
        out[kind] = out.get(kind, 0) + 1
    return out


def competitors(db, ph):
    """NPC companies visible to players."""
    import npc
    result = []
    for persona in npc.PERSONAS:
        h = holdings(db, ph, persona["owner"])
        result.append({"owner": persona["owner"], "name": persona["name"], "buildings": sum(h.values()), "holdings": h})
    return result


def wallet(db, ph, owner, clk, now):
    advance(db, ph, clk, now)
    bal = economy.ensure_wallet(db, ph, owner, now)
    quotes = quote(db, ph, clk)
    return {"ok": True, "balance": bal, "currency": economy.CURRENCY, "transactions": economy.history(db, ph, owner),
            "forecast": forecast(db, ph, owner, quotes), "reports": reports(db, ph, owner), "month_index": clk["month_index"],
            "market": quotes, "inventory": inventory_view(db, ph, owner), "holdings": holdings(db, ph, owner)}
