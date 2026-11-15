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
import json

import bank
import city
import economy
import goods_catalog
import taxes


def _q(sql, ph):
    return sql.replace("%s", ph)


def _spec(kind):
    spec = economy.PRODUCTION.get(kind)
    if spec is not None:
        return spec
    return goods_catalog.production_spec(kind)


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


def _month_products(companies):
    """Legacy clearing order, plus catalog goods that somebody actually produces, consumes or stores.

    With no agro or extraction buildings this is exactly ``product_order()`` (honey, oil, goods).
    """
    order = list(product_order())
    seen = set(order)
    live = set()
    for company in companies.values():
        for product, qty in company.get("stock", {}).items():
            if qty and product not in seen and goods_catalog.has_good(product):
                live.add(product)
        for reg in company.get("regional", {}).values():
            for kind, _factor in reg.get("buildings", ()):
                spec = _spec(kind) or {}
                product = spec.get("product")
                if product and product not in seen:
                    live.add(product)
                for raw in spec.get("inputs", {}):
                    if raw not in seen:
                        live.add(raw)
    return order + [product for product in goods_catalog.product_order() if product in live and product not in seen]


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


def _regional_price(db, ph, region, product, month):
    """Price of a city's market in `month`. The game city falls back to the national row (older databases have no regional rows)."""
    import regions
    price = regions.previous_price(db, ph, region, product, month + 1)
    if price is None and region == regions.HOME:
        price = _price_row(db, ph, product, month)
    return price


def _hold_share(db, ph, product, month, ref, region="ufa"):
    """Share (0..1) of the output a warehouse holds back, from the average price of the last months (smoothed against whipsaw)."""
    rows = [_regional_price(db, ph, region, product, month - 1 - i) for i in range(economy.HOLD_SMOOTH_MONTHS)]
    rows = [r for r in rows if r is not None]
    if not rows:
        return 0.0
    threshold = ref * economy.HOLD_BELOW
    average = sum(rows) / len(rows)
    if average >= threshold:
        return 0.0
    return min(1.0, (threshold - average) / (threshold * economy.HOLD_DEPTH))


def _save_inventory(db, ph, owner, stock):
    for product, qty in sorted(stock.items()):
        db.execute(_q("INSERT INTO inventory(owner,product,qty) VALUES(%s,%s,%s) ON CONFLICT(owner,product) DO UPDATE SET qty=excluded.qty", ph),
                   (owner, product, qty))


CHUNK = 12
_STATUS_COLS = "missed,wages_owed,input_owed,maint_owed,bankruptcies,last_bankruptcy_month,written_off"


def _status(db, ph, owner):
    row = db.execute(_q("SELECT " + _STATUS_COLS + " FROM company_status WHERE owner=%s", ph), (owner,)).fetchone()
    keys = _STATUS_COLS.split(",")
    st = dict(zip(keys, row)) if row else {"missed": 0, "wages_owed": 0, "input_owed": 0, "maint_owed": 0, "bankruptcies": 0,
                                           "last_bankruptcy_month": None, "written_off": 0}
    st.update(taxes.state(db, ph, owner))          # tax_owed, vat_credit
    return st


def _arrears(st):
    return st["wages_owed"] + st["input_owed"] + st["maint_owed"] + st["tax_owed"]


def _save_status(db, ph, owner, st):
    db.execute(_q("INSERT INTO company_status(owner," + _STATUS_COLS + ") VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(owner) DO UPDATE SET "
                  "missed=excluded.missed,wages_owed=excluded.wages_owed,input_owed=excluded.input_owed,maint_owed=excluded.maint_owed,"
                  "bankruptcies=excluded.bankruptcies,last_bankruptcy_month=excluded.last_bankruptcy_month,written_off=excluded.written_off", ph),
               (owner, st["missed"], st["wages_owed"], st["input_owed"], st["maint_owed"], st["bankruptcies"], st["last_bankruptcy_month"], st["written_off"]))


def _remove_building(db, ph, object_id, owner):
    """Take a building off the map and tell clients (one `building_removed` event per affected chunk)."""
    cells = [(int(x), int(y)) for x, y in db.execute(_q("SELECT x,y FROM cells WHERE object_id=%s", ph), (object_id,)).fetchall()]
    db.execute(_q("DELETE FROM cells WHERE object_id=%s", ph), (object_id,))
    db.execute(_q("DELETE FROM buildings WHERE id=%s", ph), (object_id,))
    db.execute(_q("DELETE FROM building_ops WHERE object_id=%s", ph), (object_id,))
    import deposits
    deposits.release(db, ph, object_id)
    grouped = {}
    for x, y in cells:
        grouped.setdefault((x // CHUNK, y // CHUNK), []).append([x, y])
    events = []
    for (cx, cy), coords in sorted(grouped.items()):
        db.execute(_q("INSERT INTO chunks(cx,cy,version) VALUES(%s,%s,1) ON CONFLICT(cx,cy) DO UPDATE SET version=chunks.version+1", ph), (cx, cy))
        version = db.execute(_q("SELECT version FROM chunks WHERE cx=%s AND cy=%s", ph), (cx, cy)).fetchone()[0]
        data = {"object_id": object_id, "owner": owner, "cells": coords}
        db.execute(_q("INSERT INTO events(cx,cy,version,kind,payload) VALUES(%s,%s,%s,%s,%s)", ph), (cx, cy, version, "building_removed", json.dumps(data)))
        events.append({"cx": cx, "cy": cy, "version": version, "kind": "building_removed", **data})
    return events


def liquidate(db, ph, owner, month, now):
    """Bankruptcy: remove all buildings, sell assets, pay creditors, write off the rest of the debt."""
    st = _status(db, ph, owner)
    account = economy.player_account(owner)
    proceeds = 0
    for object_id, kind in db.execute(_q("SELECT id,kind FROM buildings WHERE owner=%s", ph), (owner,)).fetchall():
        proceeds += int(economy.BUILD_COST.get(kind, 0) * economy.LIQUIDATION_RATE)
        _remove_building(db, ph, object_id, owner)
    db.execute(_q("DELETE FROM building_ops WHERE owner=%s", ph), (owner,))
    stock_value = 0
    for product, qty in db.execute(_q("SELECT product,qty FROM inventory WHERE owner=%s", ph), (owner,)).fetchall():
        row = db.execute(_q("SELECT price FROM market_prices WHERE product=%s ORDER BY month_index DESC LIMIT 1", ph), (product,)).fetchone()
        stock_value += int(qty * (row[0] if row else economy.reference_price(product)) * economy.INVENTORY_LIQUIDATION_RATE)
    db.execute(_q("DELETE FROM inventory WHERE owner=%s", ph), (owner,))
    if proceeds:
        economy.post(db, ph, "liquidation", "Банкротство: продажа зданий", [(economy.CONSTRUCTION, -proceeds), (account, proceeds)], now)
    if stock_value:
        economy.post(db, ph, "liquidation", "Банкротство: продажа запасов", [(economy.MARKET_ACCOUNT, -stock_value), (account, stock_value)], now)
    cash = economy.balance(db, ph, owner) or 0
    pay_w = min(st["wages_owed"], cash)
    pay_t = min(st["tax_owed"], cash - pay_w)
    pay_i = min(st["input_owed"], cash - pay_w - pay_t)
    pay_m = min(st["maint_owed"], cash - pay_w - pay_t - pay_i)
    paid = pay_w + pay_t + pay_i + pay_m
    if paid:
        economy.post(db, ph, "liquidation", "Банкротство: расчёт с кредиторами", [(account, -paid), (economy.RESIDENTS, pay_w), (economy.player_account(economy.CITY), pay_t),
                                                                                (economy.MARKET_ACCOUNT, pay_i), (economy.UPKEEP, pay_m)], now)
    owed = _arrears(st)
    loan = bank.balance(db, ph, owner)
    pay_bank = min(loan, cash - paid)
    if pay_bank:
        economy.post(db, ph, "liquidation", "Банкротство: погашение кредита", [(account, -pay_bank), (economy.BANK, pay_bank)], now)
        bank._change(db, ph, owner, d_balance=-pay_bank, d_repaid=pay_bank)
    lost_to_bank = bank.write_off(db, ph, owner, now)
    st.update(missed=0, wages_owed=0, input_owed=0, maint_owed=0, tax_owed=0, bankruptcies=st["bankruptcies"] + 1,
              last_bankruptcy_month=month, written_off=st["written_off"] + (owed - paid) + lost_to_bank)
    _save_status(db, ph, owner, st)
    taxes.save_state(db, ph, owner, st)
    import contracts as trade_contracts
    trade_contracts.on_bankruptcy(db, ph, owner, month, now)


def sell_building(db, ph, owner, object_id, now):
    """Voluntary sale of one building at SELL_RATE of its construction cost. Returns (status, result)."""
    row = db.execute(_q("SELECT owner,kind FROM buildings WHERE id=%s", ph), (object_id,)).fetchone()
    if row is None:
        return 404, {"error": "not_found"}
    if row[0] != owner:
        return 403, {"error": "not_owner"}
    kind = row[1]
    price = int(economy.BUILD_COST.get(kind, 0) * economy.SELL_RATE)
    events = _remove_building(db, ph, object_id, owner)
    account = economy.player_account(owner)
    if price:
        economy.post(db, ph, "sale", "Продажа здания: %s" % kind, [(economy.CONSTRUCTION, -price), (account, price)], now)
    # Stock above the remaining warehouse capacity cannot stay: it is sold at the liquidation share of the market price.
    capacity = sum(_spec(k)["capacity"] for k, in db.execute(_q("SELECT kind FROM building_ops WHERE owner=%s", ph), (owner,)).fetchall()
                   if _spec(k) and _spec(k).get("capacity"))
    stock = {p: int(q) for p, q in db.execute(_q("SELECT product,qty FROM inventory WHERE owner=%s", ph), (owner,)).fetchall() if q > 0}
    excess = sum(stock.values()) - capacity
    sold_value = 0
    for product in sorted(stock, key=lambda k: -stock[k]):
        if excess <= 0:
            break
        take = min(stock[product], excess)
        excess -= take
        last = db.execute(_q("SELECT price FROM market_prices WHERE product=%s ORDER BY month_index DESC LIMIT 1", ph), (product,)).fetchone()
        sold_value += int(take * (last[0] if last else economy.reference_price(product)) * economy.INVENTORY_LIQUIDATION_RATE)
        db.execute(_q("UPDATE inventory SET qty=%s WHERE owner=%s AND product=%s", ph), (stock[product] - take, owner, product))
    if sold_value:
        economy.post(db, ph, "sale", "Продажа лишних запасов", [(economy.MARKET_ACCOUNT, -sold_value), (account, sold_value)], now)
    if not db.execute(_q("SELECT 1 FROM building_ops WHERE owner=%s", ph), (owner,)).fetchone() and bank.balance(db, ph, owner) > 0:
        bank.repay(db, ph, owner, None, now)       # the last building is gone: sale proceeds repay the loan first
    return 201, {"ok": True, "object_id": object_id, "kind": kind, "price": price + sold_value, "balance": economy.balance(db, ph, owner), "events": events}


def labor_market(population, total_jobs):
    """Labour market of one month: staffing, wage and the demand scale produced by residents' income."""
    labor = int(population * economy.PARTICIPATION)
    staffing = 1.0 if total_jobs <= 0 else min(1.0, labor / total_jobs)
    pressure = (total_jobs / labor) if labor > 0 else 0.0
    wage = int(round(economy.BASE_WAGE * min(max(pressure ** economy.WAGE_ELASTICITY, 1.0), economy.WAGE_MAX)))
    employed = total_jobs * staffing
    income_ratio = employed * wage / (max(labor, 1) * economy.BASE_WAGE)
    w = economy.INCOME_WEIGHT
    scale = population / economy.BASE_POPULATION * (1 - w + w * min(income_ratio, economy.INCOME_CAP))
    return {"population": int(population), "labor_force": labor, "jobs": int(total_jobs), "staffing": staffing, "wage": wage,
            "employed": int(employed), "unemployment": max(0.0, (labor - employed) / max(labor, 1)), "scale": scale}


def next_population(population, total_jobs, labor, quality=0.0):
    """Population next month; social services (quality 0..1) raise growth and immigration and soften emigration."""
    shortage = max(-1.0, min(1.0, (total_jobs - labor) / max(labor, 1)))
    rate = economy.NATURAL_GROWTH + economy.SOCIAL_GROWTH * quality + (
        economy.MIGRATION_IN * (1 + quality) * shortage if shortage > 0 else economy.MIGRATION_OUT * (1 - 0.5 * quality) * shortage)
    return max(economy.MIN_POPULATION, int(round(population * (1 + rate))))


def _population_at(db, ph, month):
    """Population at the start of `month` (the previous month's migration result)."""
    row = db.execute(_q("SELECT next_population FROM population WHERE month_index=%s", ph), (month - 1,)).fetchone()
    if row is None:
        row = db.execute("SELECT next_population FROM population ORDER BY month_index DESC LIMIT 1").fetchone()
    return int(row[0]) if row else economy.BASE_POPULATION


def step_month(db, ph, month, now):
    """Run the market step for one completed month."""
    import regions
    active = regions.active_regions(db, ph)                      # the game city, cities with company buildings, generated cities
    where = regions.building_regions(db, ph)
    ops = db.execute(_q("SELECT owner,kind,start_month,start_permille,object_id FROM building_ops WHERE start_month<=%s", ph), (month,)).fetchall()
    companies = {}
    for owner, kind, start_month, permille, object_id in sorted(ops):
        spec = _spec(kind)
        if spec is None:
            continue
        c = companies.setdefault(owner, {"buildings": [], "maint": 0, "jobs": 0, "capacity": 0, "stock": {}, "needs": {}, "got": {},
                                         "need_ext": {}, "revenue": 0, "input_cost": 0, "rev_by": {}, "in_by": {}, "regional": {}})
        factor = _factor(start_month, permille, month)
        region = where.get(object_id, regions.HOME)
        reg = c["regional"].setdefault(region, {"buildings": [], "jobs": 0, "needs": {}, "got": {}, "need_ext": {}})
        c["buildings"].append((kind, factor))
        reg["buildings"].append((kind, factor))
        if goods_catalog.deposit_resource(kind):
            reg.setdefault("wells", []).append((object_id, kind, factor))
        c["maint"] += spec["upkeep"] * factor // 1000
        c["jobs"] += spec["jobs"] * factor // 1000
        reg["jobs"] += spec["jobs"] * factor // 1000
        c["capacity"] += spec.get("capacity", 0)
        for product, amount in spec.get("inputs", {}).items():
            c["needs"][product] = c["needs"].get(product, 0) + amount * factor // 1000
            reg["needs"][product] = reg["needs"].get(product, 0) + amount * factor // 1000
    for owner, product, qty in db.execute("SELECT owner,product,qty FROM inventory").fetchall():
        if owner in companies:
            companies[owner]["stock"][product] = int(qty)
    for owner, c in companies.items():
        c["cash"] = economy.balance(db, ph, owner) or 0
        c["distress"] = _status(db, ph, owner)["missed"] >= 1      # unpaid last month: workers walk away
        # the city where the company keeps its stock (warehouses are notional): most jobs, ties by the order of the cities
        c["home"] = sorted(c["regional"], key=lambda r: (-(c["regional"][r]["jobs"] + len(c["regional"][r]["buildings"])), regions.region_ids().index(r)))[0] \
            if c["regional"] else regions.HOME

    # every active city has its own residents, labour market, wage and staffing
    pop_r, jobs_r, lab_r, staffing_r = {}, {}, {}, {}
    for region in active:
        pop_r[region] = _population_at(db, ph, month) if region == regions.HOME else regions.population_at(db, ph, region, month)
        jobs_r[region] = sum(c["regional"][region]["jobs"] for c in companies.values() if region in c["regional"])
        lab_r[region] = labor_market(pop_r[region], jobs_r[region])
        staffing_r[region] = lab_r[region]["staffing"]
    population, total_jobs, lab, staffing = pop_r[regions.HOME], jobs_r[regions.HOME], lab_r[regions.HOME], staffing_r[regions.HOME]
    city.ensure(db, ph, month)
    soc = city.social(db, ph, month, population, funded=_arrears(_status(db, ph, economy.CITY)) == 0)
    quality = soc["quality"]
    quality_r = {region: (quality if region == regions.HOME else 0.0) for region in active}    # social services exist in the game city only
    for c in companies.values():
        for region, reg in c["regional"].items():
            for product in list(reg["needs"]):
                reg["needs"][product] = int(reg["needs"][product] * staffing_r[region])   # understaffed factories also use less input
        c["needs"] = {}
        for reg in c["regional"].values():
            for product, amount in reg["needs"].items():
                c["needs"][product] = c["needs"].get(product, 0) + amount
        c["wage_bill"] = sum(reg["jobs"] * lab_r[region]["wage"] for region, reg in c["regional"].items())

    consumed = input_products() | goods_catalog.all_inputs()
    prices = {}
    import contracts as trade_contracts
    import deposits
    well_left = deposits.load_remaining(db, ph)
    contract_deliveries = []
    spend_r = {region: 0 for region in active}       # value of what each city's residents bought (consumer demand x fill x price)
    units_r = {region: 0 for region in active}       # units of consumer goods behind that value (shops serve these)
    consumer_spend = 0
    for product in _month_products(companies):
        ref = economy.market_of(product)["reference_price"]
        hold_share = _hold_share(db, ph, product, month, ref)
        previous = _price_row(db, ph, product, month - 1)
        release_all = previous is not None and previous >= ref       # price above the reference: the warehouse sells everything
        produced_by = {}
        produced_map = {}
        for owner, c in companies.items():
            by_region = {}
            for region, reg in c["regional"].items():
                produced = 0
                for kind, factor in reg["buildings"]:
                    spec = _spec(kind)
                    if not spec or spec.get("product") != product:
                        continue
                    if goods_catalog.deposit_resource(kind):
                        continue
                    out = spec["output"] * factor // 1000
                    scale = _input_fraction_for(reg, spec["inputs"]) if spec.get("inputs") else 1.0
                    out = int(out * staffing_r[region] * scale * (economy.DISTRESS_OUTPUT if c["distress"] else 1.0)
                              * (1 + economy.SOCIAL_PRODUCTIVITY * quality_r[region]))
                    produced += out
                for object_id, kind, factor in reg.get("wells", ()):
                    spec = _spec(kind)
                    if not spec or spec.get("product") != product:
                        continue
                    out = spec["output"] * factor // 1000
                    out = int(out * staffing_r[region] * (economy.DISTRESS_OUTPUT if c["distress"] else 1.0)
                              * (1 + economy.SOCIAL_PRODUCTIVITY * quality_r[region]))
                    produced += deposits.draw(well_left, object_id, out)
                by_region[region] = produced
            produced_by[owner] = by_region
            produced_map[owner] = sum(by_region.values())
        before = dict(produced_map)
        contract_deliveries.extend(trade_contracts.deliver(db, ph, product, month, companies, produced_map))
        for owner, c in companies.items():                    # a buyer without buildings is a shell company in the game city
            c.setdefault("regional", {})
            c.setdefault("home", regions.HOME)
            by_region = produced_by.setdefault(owner, {})
            total = before.get(owner, 0)
            now_total = produced_map.get(owner, 0)
            if now_total != total:                            # contracts took goods before the market: every branch gives its proportional share
                left = now_total
                keys = sorted(by_region, key=regions.region_ids().index)
                for i, region in enumerate(keys):
                    by_region[region] = left if i == len(keys) - 1 else int(by_region[region] * now_total / total) if total else 0
                    left -= by_region[region]
                if not keys and now_total:
                    by_region[c["home"]] = now_total
        offers_r = {region: {} for region in active}
        need_ext_r = {region: 0 for region in active}
        for owner, c in companies.items():
            home = c["home"] if c["home"] in offers_r else regions.HOME
            stock = c["stock"].get(product, 0)                   # the warehouse stands in the company's home city
            c_regions = set(c["regional"]) | {home}
            for region in sorted(c_regions, key=regions.region_ids().index):
                if region not in offers_r:
                    continue
                reg = c["regional"].get(region)
                produced = produced_by.get(owner, {}).get(region, 0)
                local_stock = stock if region == home else 0
                need = reg["needs"].get(product, 0) if reg else 0
                if product in consumed and need:
                    internal = min(need, produced + local_stock)          # own supply first, no market purchase
                    from_prod = min(internal, produced)
                    produced -= from_prod
                    local_stock -= internal - from_prod
                    reg["got"][product] = internal
                    reg["need_ext"][product] = need - internal
                    c["got"][product] = c["got"].get(product, 0) + internal
                    c["need_ext"][product] = c["need_ext"].get(product, 0) + need - internal
                    need_ext_r[region] += need - internal
                if region == home:
                    # A warehouse never starves the company of cash: it holds stock only while two months of costs are covered.
                    runway = c["cash"] >= 2 * (c["maint"] + int(c.get("wage_bill", 0)))
                    if c["capacity"] > 0 and hold_share > 0 and runway:
                        free = max(0, c["capacity"] - sum(v for k, v in c["stock"].items() if k != product) - local_stock)
                        held = min(int(produced * hold_share), free)
                        released = int(local_stock * economy.RELEASE_SHARE * (1 - hold_share))     # a falling market releases less
                        local_stock += held - released
                        offers_r[region][owner] = produced - held + released
                    elif c["capacity"] > 0 and not release_all and local_stock > 0:
                        released = int(local_stock * economy.RELEASE_SHARE) or local_stock                # gradual release, never an all-at-once dump
                        local_stock -= released
                        offers_r[region][owner] = produced + released
                    else:
                        offers_r[region][owner] = produced + local_stock
                        local_stock = 0
                    c["stock"][product] = local_stock
                else:
                    offers_r[region][owner] = produced + local_stock
        # ---- every city clears its own market; surplus travels to dearer cities and arrives after the transit time ----
        arriving = regions.arrivals(db, ph, product, month) if len(active) > 1 else {}
        offered = {region: sum(offers_r[region].values()) for region in active}
        demand_local = {region: economy.demand_for(product, month, lab_r[region]["scale"]) + need_ext_r[region] for region in active}
        sent = {region: 0 for region in active}
        received = {region: arriving.get(region, 0) for region in active}
        transport_by, freight_by = {}, {}
        if len(active) > 1:
            prev_r = {}
            for region in active:
                prev = _regional_price(db, ph, region, product, month - 1)
                prev_r[region] = prev if prev is not None else ref
            plan = regions.plan_exports(product, active, offered, demand_local, arriving, prev_r, regions.pipeline(db, ph, product))
            for origin, destination, qty in plan:
                total_offer = sum(offers_r[origin].values())
                qty = min(qty, total_offer)
                if qty <= 0:
                    continue
                shares = _split_units(offers_r[origin], qty)
                for owner, taken in shares.items():
                    offers_r[origin][owner] -= taken
                    transport_by[(owner, origin)] = transport_by.get((owner, origin), 0) + taken
                    freight_by[(owner, origin)] = freight_by.get((owner, origin), 0) + taken * regions.unit_cost(product, origin, destination)
                if regions.dispatch(db, ph, product, origin, destination, qty, month, "ship:%d:%s:%s:%s" % (month, product, origin, destination)):
                    received[destination] += qty              # a trip of hours: the goods are in the destination's market this month
                sent[origin] += qty
        price_r, fill_r, supply_r = {}, {}, {}
        for region in active:
            supply = sum(offers_r[region].values()) + received[region]
            demand = demand_local[region]
            price = economy.price_for(product, supply, demand)
            price_r[region], supply_r[region] = price, supply
            fill = 1.0 if demand <= 0 else min(1.0, supply / demand)
            fill_r[region] = fill
            consumer_part = demand - need_ext_r[region]
            spend_r[region] += int(consumer_part * fill * price)
            consumer_spend += int(consumer_part * fill * price)
            if economy.market_of(product).get("consumer"):
                units_r[region] += int(consumer_part * fill)
            for owner, c in companies.items():
                sold = offers_r[region].get(owner, 0) + transport_by.get((owner, region), 0)       # shipped goods are paid at the home price
                if owner in offers_r[region]:
                    revenue = sold * price - freight_by.get((owner, region), 0)       # the exporter pays the carriage
                    c["revenue"] += revenue
                    c["rev_by"][product] = c["rev_by"].get(product, 0) + revenue
                reg = c["regional"].get(region)
                ext = reg["need_ext"].get(product, 0) if reg else 0
                if ext:
                    bought = int(ext * fill)
                    reg["got"][product] = reg["got"].get(product, 0) + bought
                    c["got"][product] = c["got"].get(product, 0) + bought
                    c["input_cost"] += bought * price
                    c["in_by"][product] = c["in_by"].get(product, 0) + bought * price
            db.execute(_q("INSERT INTO market_prices_region(region,product,month_index,price,supply,demand,imports,exports) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) "
                          "ON CONFLICT(region,product,month_index) DO NOTHING", ph), (region, product, month, price, supply, demand, received[region], sent[region]))
        total_supply = sum(supply_r.values())
        total_demand = sum(demand_local.values())
        if len(active) == 1:
            price = price_r[active[0]]
        else:
            weight = sum(demand_local[r] for r in active) or 1
            price = int(round(sum(price_r[r] * demand_local[r] for r in active) / weight)) if weight > 1 else price_r[regions.HOME]
        prices[product] = price
        db.execute(_q("INSERT INTO market_prices(product,month_index,price,supply,demand) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(product,month_index) DO NOTHING", ph),
                   (product, month, price, total_supply, total_demand))

    import retail
    for region in active:                                      # shops serve the residents of their own city
        shims = {owner: {"buildings": c["regional"][region]["buildings"], "revenue": 0, "rev_by": {}}
                 for owner, c in companies.items() if region in c["regional"]}
        if retail.apply(shims, spend_r[region], units_r[region], staffing_r[region]):
            for owner, shim in shims.items():
                companies[owner]["revenue"] += shim["revenue"]
                for key, value in shim["rev_by"].items():
                    companies[owner]["rev_by"][key] = companies[owner]["rev_by"].get(key, 0) + value

    loans = {o: int(b) for o, b in db.execute("SELECT owner,balance FROM loans WHERE balance>0").fetchall()}
    rates = taxes.rates(db, ph)
    budget = economy.player_account(economy.CITY)
    bankrupt = []
    for owner, c in sorted(companies.items()):
        st = _status(db, ph, owner)
        is_city = owner == economy.CITY
        wages = int(sum(reg["jobs"] * staffing_r[region] * lab_r[region]["wage"] for region, reg in c.get("regional", {}).items()))
        interest_due = bank.monthly_interest(loans.get(owner, 0))
        # VAT: buyers pay price + VAT, the company pays VAT on its raw materials (gross flows through the cash cascade)
        vat_out, vat_in = taxes.vat_amounts(c["rev_by"], c["in_by"]) if not is_city else (0, 0)
        revenue_g, input_g = c["revenue"] + vat_out, c["input_cost"] + vat_in
        cash = (economy.balance(db, ph, owner) or 0) + revenue_g
        paid_input = min(input_g, max(cash, 0))
        cash -= paid_input
        paid_wages = min(wages, max(cash, 0))
        cash -= paid_wages
        paid_maint = min(c["maint"], max(cash, 0))
        cash -= paid_maint
        paid_interest = min(interest_due, max(cash, 0))
        cash -= paid_interest
        # taxes (the city itself pays none)
        net_vat = vat_out - vat_in - st["vat_credit"]
        vat_due = max(net_vat, 0)
        st["vat_credit"] = max(-net_vat, 0)
        taxable = c["revenue"] - c["input_cost"] - wages - c["maint"] - interest_due
        profit_tax = 0 if is_city else taxes.profit_tax_due(taxable, rates["profit"])
        property_tax = 0 if is_city else taxes.property_tax_due(c["buildings"], rates["property"])
        tax_due = vat_due + profit_tax + property_tax
        paid_tax = min(tax_due, max(cash, 0))
        cash -= paid_tax
        unpaid = {"input": input_g - paid_input, "wages": wages - paid_wages, "maint": c["maint"] - paid_maint,
                  "interest": interest_due - paid_interest, "tax": tax_due - paid_tax}
        bank.paid_interest(db, ph, owner, paid_interest)
        bank.capitalize(db, ph, owner, unpaid["interest"])
        # leftover cash services old arrears: wages first, then taxes, raw materials, maintenance
        arr_w = min(st["wages_owed"], max(cash, 0))
        cash -= arr_w
        arr_t = min(st["tax_owed"], max(cash, 0))
        cash -= arr_t
        arr_i = min(st["input_owed"], max(cash, 0))
        cash -= arr_i
        arr_m = min(st["maint_owed"], max(cash, 0))
        cash -= arr_m
        st["wages_owed"] += unpaid["wages"] - arr_w
        st["tax_owed"] += unpaid["tax"] - arr_t
        st["input_owed"] += unpaid["input"] - arr_i
        st["maint_owed"] += unpaid["maint"] - arr_m
        st["missed"] = st["missed"] + 1 if sum(unpaid.values()) > 0 and not is_city else 0
        c["after_tax"] = c["revenue"] - c["input_cost"] - wages - c["maint"] - interest_due - profit_tax - property_tax
        c["unpaid_sum"] = sum(unpaid.values())
        c["reserve"] = (c["maint"] + wages + c["input_cost"]) * economy.OWNER_SPEND_RESERVE_MONTHS
        out_input, out_wages, out_maint, out_tax = paid_input + arr_i, paid_wages + arr_w, paid_maint + arr_m, paid_tax + arr_t
        profit = c["revenue"] - c["input_cost"] - paid_wages - paid_maint
        if revenue_g or out_input or out_wages or out_maint or paid_interest or out_tax:
            economy.post(db, ph, "monthly", "Итоги месяца: доход %d, сырьё %d, зарплаты %d, обслуживание %d%s%s%s" % (
                             c["revenue"], out_input, out_wages, out_maint, (", налоги %d" % out_tax) if out_tax else "",
                             (", проценты %d" % paid_interest) if paid_interest else "",
                             (", долг %d" % _arrears(st)) if st["missed"] or _arrears(st) else ""),
                         [(economy.player_account(owner), revenue_g - out_input - out_wages - out_maint - paid_interest - out_tax),
                          (economy.MARKET_ACCOUNT, -revenue_g + out_input), (economy.RESIDENTS, out_wages), (economy.UPKEEP, out_maint),
                          (economy.BANK, paid_interest), (budget, out_tax)] if owner != economy.CITY else
                         [(budget, revenue_g - out_input - out_wages - out_maint - paid_interest - out_tax),
                          (economy.MARKET_ACCOUNT, -revenue_g + out_input), (economy.RESIDENTS, out_wages), (economy.UPKEEP, out_maint),
                          (economy.BANK, paid_interest)], now)
        db.execute(_q("INSERT INTO company_reports(owner,month_index,revenue,input_cost,upkeep,profit,buildings) VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(owner,month_index) DO NOTHING", ph),
                   (owner, month, c["revenue"], min(c["input_cost"], paid_input), paid_wages + paid_maint, profit, len(c["buildings"])))
        taxes.record(db, ph, owner, month, vat_due, profit_tax, property_tax, out_tax)
        _save_status(db, ph, owner, st)
        taxes.save_state(db, ph, owner, st)
        _save_inventory(db, ph, owner, c["stock"])
        if st["missed"] >= economy.BANKRUPT_AFTER_MISSED and not is_city:
            bankrupt.append(owner)
    for owner, loan_balance in sorted(loans.items()):
        if owner in companies:
            continue
        due = bank.monthly_interest(loan_balance)
        paid = min(due, max(economy.balance(db, ph, owner) or 0, 0))
        if paid:
            economy.post(db, ph, "monthly", "Проценты по кредиту %d" % paid, [(economy.player_account(owner), -paid), (economy.BANK, paid)], now)
        bank.paid_interest(db, ph, owner, paid)
        bank.capitalize(db, ph, owner, due - paid)
    trade_contracts.settle(db, ph, month, contract_deliveries, now, bankrupt)
    import owner_spend
    owner_spend.settle(db, ph, month, companies, bankrupt, now)
    if economy.RESIDENT_SPEND_TO_MARKET and consumer_spend > 0:
        row = db.execute(_q("SELECT balance FROM wallets WHERE account=%s", ph), (economy.RESIDENTS,)).fetchone()
        spend = min(consumer_spend, max(0, int(row[0]) if row else 0))
        if spend:
            economy.post(db, ph, "residents", "Жители потратили зарплату на товары: %d" % spend, [(economy.RESIDENTS, -spend), (economy.MARKET_ACCOUNT, spend)], now)
    for owner in bankrupt:
        liquidate(db, ph, owner, month, now)
    city.monthly(db, ph, month, now)
    city_cash = economy.balance(db, ph, economy.CITY) or 0
    services = sum(economy.monthly_cost(k, lab["wage"]) for k, in db.execute(_q("SELECT kind FROM building_ops WHERE owner=%s", ph), (economy.CITY,)).fetchall())
    health = 0.0 if _arrears(_status(db, ph, economy.CITY)) > 0 else (1.0 if services <= 0 else min(1.0, city_cash / (2.0 * services)))
    city.update_rating(db, ph, month, quality, lab["unemployment"], health, now)
    city.tally_if_due(db, ph, month, lab["population"], lab["unemployment"], quality, now)
    next_pop = next_population(population, total_jobs, lab["labor_force"], quality)
    db.execute(_q("INSERT INTO population(month_index,population,labor_force,jobs,wage,staffing_permille,demand_permille,next_population) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(month_index) DO NOTHING", ph),
               (month, lab["population"], lab["labor_force"], lab["jobs"], lab["wage"], int(staffing * 1000), int(lab["scale"] * 1000), next_pop))
    # Once the game city has been generated (docs/CITYGEN.md) its houses follow the population; a no-op before that.
    import citygen
    citygen.grow(db, ph, next_pop, now)
    # the other active cities: their own residents, jobs and wage (no social services there yet, docs/CITY_ECONOMY.md)
    for region in active:
        if region != regions.HOME:
            nxt = next_population(pop_r[region], jobs_r[region], lab_r[region]["labor_force"], 0.0)
            regions.save_population(db, ph, region, month, lab_r[region], staffing_r[region], nxt)
    deposits.store_remaining(db, ph, well_left)


def _split_units(offers, qty):
    """Take `qty` units from the sellers' offers in proportion (largest remainder; deterministic by owner name)."""
    total = sum(offers.values())
    out = {o: int(qty * v // total) if total else 0 for o, v in offers.items()}
    left = qty - sum(out.values())
    for o in sorted(offers, key=lambda k: (-(qty * offers[k] % total if total else 0), k)):
        if left <= 0:
            break
        if out[o] < offers[o]:
            out[o] += 1
            left -= 1
    return {o: v for o, v in out.items() if v > 0}


def _input_fraction(c):
    """Share of full capacity a company's factories can run at, limited by the scarcest input."""
    fraction = 1.0
    for product, need in c["needs"].items():
        if need > 0:
            fraction = min(fraction, c["got"].get(product, 0) / need)
    return fraction


def _input_fraction_for(reg, inputs):
    """Same ratio as ``_input_fraction``, but only for this building's own inputs.

    A mill's missing grain must not throttle a factory that shares the region: the
    legacy factory only depends on oil and honey, and those are the only keys in
    ``reg["needs"]`` when no other input-using building is present.
    """
    fraction = 1.0
    for product in inputs:
        need = reg["needs"].get(product, 0)
        if need > 0:
            fraction = min(fraction, reg["got"].get(product, 0) / need)
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


def _current_labor(db, ph, month, ops):
    """Provisional labour market of the running month (all buildings at full capacity)."""
    jobs = sum(economy.kind_jobs(k) for _o, k, sm, _p in ops if sm <= month)
    population = _population_at(db, ph, month)
    lab = labor_market(population, jobs)
    lab["social"] = city.social(db, ph, month, population, funded=_arrears(_status(db, ph, economy.CITY)) == 0)
    lab["quality"] = lab["social"]["quality"]
    return lab


def labor_view(db, ph, clk):
    lab = _current_labor(db, ph, clk["month_index"], _ops(db, ph))
    return {"population": lab["population"], "labor_force": lab["labor_force"], "jobs": lab["jobs"], "employed": lab["employed"],
            "wage": lab["wage"], "base_wage": economy.BASE_WAGE, "staffing": round(lab["staffing"], 3), "unemployment": round(lab["unemployment"], 3),
            "quality": round(lab["quality"], 3), "scale": round(lab["scale"], 3)}


def quote(db, ph, clk):
    """Provisional market state for the running month, plus the price if one more producer were added."""
    month = clk["month_index"]
    ops = _ops(db, ph)
    lab = _current_labor(db, ph, month, ops)
    out = {}
    for product in product_order():
        producing_kind = next(k for k, s in economy.PRODUCTION.items() if s.get("product") == product)
        output = economy.PRODUCTION[producing_kind]["output"]
        base = sum(economy.PRODUCTION[k]["output"] for _, k, sm, _p in ops if k in economy.PRODUCTION and economy.PRODUCTION[k].get("product") == product and sm <= month)
        extra = sum((_spec(k) or {}).get("output", 0) for _, k, sm, _p in ops if k not in economy.PRODUCTION and sm <= month and (_spec(k) or {}).get("product") == product)
        supply = int((base + extra) * lab["staffing"] * (1 + economy.SOCIAL_PRODUCTIVITY * lab["quality"]))
        need_base = sum(n for _, k, sm, _p in ops if k in economy.PRODUCTION and sm <= month for p, n in economy.PRODUCTION.get(k, {}).get("inputs", {}).items() if p == product)
        need_extra = sum(n for _, k, sm, _p in ops if k not in economy.PRODUCTION and sm <= month for p, n in (_spec(k) or {}).get("inputs", {}).items() if p == product)
        need = int((need_base + need_extra) * lab["staffing"])
        demand = economy.demand_for(product, month, lab["scale"]) + need
        m = economy.MARKET[product]
        out[product] = {"kind": producing_kind, "name": m["name"], "reference_price": m["reference_price"], "supply": supply, "demand": demand,
                        "price": economy.price_for(product, supply, demand), "price_if_added": economy.price_for(product, supply + output, demand),
                        "previous_price": _price_row(db, ph, product, month - 1)}
    live = set()
    for _o, k, sm, _p in ops:
        if sm > month:
            continue
        spec = _spec(k) or {}
        if k in economy.PRODUCTION:
            continue
        if spec.get("product"):
            live.add(spec["product"])
        live.update(spec.get("inputs", ()))
    for product in goods_catalog.product_order():
        if product not in live or product in out:
            continue
        producing_kind = goods_catalog.producer_kind(product)
        output = goods_catalog.recipe(producing_kind).capacity
        made = sum((_spec(k) or {}).get("output", 0) for _, k, sm, _p in ops if sm <= month and (_spec(k) or {}).get("product") == product)
        need = sum(n for _, k, sm, _p in ops if sm <= month for p, n in (_spec(k) or {}).get("inputs", {}).items() if p == product)
        supply = int(made * lab["staffing"] * (1 + economy.SOCIAL_PRODUCTIVITY * lab["quality"]))
        demand = economy.demand_for(product, month, lab["scale"]) + int(need * lab["staffing"])
        m = economy.market_of(product)
        out[product] = {"kind": producing_kind, "name": m["name"], "reference_price": m["reference_price"], "supply": supply, "demand": demand,
                        "price": economy.price_for(product, supply, demand), "price_if_added": economy.price_for(product, supply + output, demand),
                        "previous_price": _price_row(db, ph, product, month - 1)}
    return out


def forecast(db, ph, owner, quotes, labor):
    """Expected monthly result at current prices and wages (all production sold, all inputs bought)."""
    revenue = inputs = maint = wages = count = 0
    staffing = labor["staffing"]
    kinds = []
    for kind, in db.execute(_q("SELECT kind FROM building_ops WHERE owner=%s", ph), (owner,)).fetchall():
        kinds.append((kind, 1000))
        spec = _spec(kind)
        if not spec:
            continue
        if spec.get("product"):
            price = quotes[spec["product"]]["price"] if spec["product"] in quotes else economy.market_of(spec["product"])["reference_price"]
            revenue += int(spec["output"] * staffing * price)
        for product, amount in spec.get("inputs", {}).items():
            price = quotes[product]["price"] if product in quotes else economy.market_of(product)["reference_price"]
            inputs += int(amount * staffing * price)
        maint += spec["upkeep"]
        wages += int(economy.kind_jobs(kind) * staffing * labor["wage"])
        count += 1
    interest = bank.monthly_interest(bank.balance(db, ph, owner))
    profit = revenue - inputs - maint - wages - interest
    rates = taxes.rates(db, ph)
    profit_tax = taxes.profit_tax_due(profit, rates["profit"]) if owner != economy.CITY else 0
    property_tax = taxes.property_tax_due(kinds, rates["property"]) if owner != economy.CITY else 0
    return {"revenue": revenue, "input_cost": inputs, "upkeep": maint + wages, "wages": wages, "interest": interest,
            "profit": profit, "profit_tax": profit_tax, "property_tax": property_tax, "profit_after_tax": profit - profit_tax - property_tax,
            "owner_spend": int(max(0, profit - profit_tax - property_tax) * economy.OWNER_SPEND_SHARE) if economy.OWNER_SPEND_ENABLED and owner != economy.CITY else 0,
            "owner_spend_share": economy.OWNER_SPEND_SHARE, "buildings": count}


def inventory_view(db, ph, owner):
    rows = db.execute(_q("SELECT product,qty FROM inventory WHERE owner=%s ORDER BY product", ph), (owner,)).fetchall()
    capacity = sum(_spec(k)["capacity"] for k, in db.execute(_q("SELECT kind FROM building_ops WHERE owner=%s", ph), (owner,)).fetchall()
                   if _spec(k) and _spec(k).get("capacity"))
    items = []
    for p, q in rows:
        if q <= 0:
            continue
        if p in economy.MARKET:
            name = economy.MARKET[p]["name"]
        elif goods_catalog.has_good(p):
            name = goods_catalog.good(p).name
        else:
            continue
        items.append({"product": p, "name": name, "qty": int(q)})
    return {"items": items, "used": sum(i["qty"] for i in items), "capacity": capacity}


def reports(db, ph, owner, limit=6):
    rows = db.execute(_q("SELECT month_index,revenue,input_cost,upkeep,profit,buildings FROM company_reports WHERE owner=%s ORDER BY month_index DESC LIMIT %s", ph),
                      (owner, limit)).fetchall()
    paid = taxes.last_taxes(db, ph, owner, limit)
    import owner_spend
    spent = owner_spend.last_for(db, ph, owner, limit)
    return [{"month_index": m, "revenue": r, "input_cost": i, "upkeep": u, "profit": p, "buildings": b,
             "tax": paid.get(int(m), {}).get("paid", 0), "owner_spent": spent.get(int(m), 0)} for m, r, i, u, p, b in rows]


def company_view(db, ph, owner):
    st = _status(db, ph, owner)
    return {"missed": st["missed"], "arrears": _arrears(st), "wages_owed": st["wages_owed"], "tax_owed": st["tax_owed"], "vat_credit": st["vat_credit"],
            "input_owed": st["input_owed"], "maint_owed": st["maint_owed"], "bankruptcies": st["bankruptcies"],
            "last_bankruptcy_month": st["last_bankruptcy_month"], "written_off": st["written_off"], "bankrupt_after": economy.BANKRUPT_AFTER_MISSED}


def loan_view(db, ph, owner):
    st = _status(db, ph, owner)
    return bank.view(db, ph, owner, in_default=st["missed"] > 0 or _arrears(st) > 0)


def loan_command(db, ph, owner, payload, now):
    """POST /loan: {action: take|repay, amount}. Returns (status, result)."""
    action = payload.get("action")
    amount = payload.get("amount")
    if action == "take":
        st = _status(db, ph, owner)
        in_default = st["missed"] > 0 or _arrears(st) > 0
        status, result = bank.take(db, ph, owner, amount, now, in_default)
    elif action == "repay":
        status, result = bank.repay(db, ph, owner, amount, now)
    else:
        return 400, {"error": "invalid_action"}
    if status in (200, 201):
        result = dict(result, balance=economy.balance(db, ph, owner), loan=loan_view(db, ph, owner))
    return status, result


def city_view(db, ph, clk, owner=None):
    """Public state of the city: mayor, budget, taxes, social services and what the budget collected last month."""
    month = clk["month_index"]
    m = city.mayor(db, ph, month)
    lab = _current_labor(db, ph, month, _ops(db, ph))
    soc = lab["social"]
    collected = db.execute(_q("SELECT COALESCE(SUM(paid),0) FROM company_taxes WHERE month_index=%s", ph), (month - 1,)).fetchone()[0]
    policy = db.execute("SELECT social_share_permille,changed_month FROM city_policy WHERE id=1").fetchone()
    buildings = [{"object_id": oid, "kind": kind, "x": x, "y": y} for oid, kind, x, y in
                 db.execute(_q("SELECT id,kind,x,y FROM buildings WHERE owner=%s ORDER BY created", ph), (economy.CITY,)).fetchall()]
    upkeep = sum(economy.monthly_cost(k, lab["wage"]) for k in [b["kind"] for b in buildings])
    return {"ok": True, "month_index": month, "mayor": m, "budget": economy.balance(db, ph, economy.CITY) or 0,
            "taxes": taxes.view(db, ph), "collected_last_month": int(collected), "services_upkeep": upkeep,
            "social": {"counts": soc["counts"], "coverage": {k: round(v, 3) for k, v in soc["coverage"].items()}, "quality": round(soc["quality"], 3), "funded": soc["funded"]},
            "costs": {k: economy.BUILD_COST[k] for k in economy.SOCIAL_KINDS}, "serves": {k: economy.PRODUCTION[k]["serves"] for k in economy.SOCIAL_KINDS},
            "salary": economy.MAYOR_SALARY, "social_share": policy[1] and policy[0] / 1000.0, "tax_changed_month": int(policy[1]), "buildings": buildings,
            "arrears": _arrears(_status(db, ph, economy.CITY)), "election": city.election_view(db, ph, month, owner),
            "rating": city.rating_view(db, ph),
            "perks": {"salary": economy.MAYOR_SALARY, "bonus_share": economy.MAYOR_BONUS_SHARE, "term_bonus": [[t, b] for t, b in economy.TERM_BONUS],
                      "max_terms": economy.MAX_CONSECUTIVE_TERMS, "terms_served": city.consecutive_terms(db, ph, m["owner"]) if not m["is_npc"] else 0},
            "terms": city.terms_view(db, ph)}


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
    labor = labor_view(db, ph, clk)
    import retail
    return {"ok": True, "balance": bal, "currency": economy.CURRENCY, "transactions": economy.history(db, ph, owner),
            "forecast": forecast(db, ph, owner, quotes, labor), "labor": labor, "reports": reports(db, ph, owner), "month_index": clk["month_index"],
            "market": quotes, "inventory": inventory_view(db, ph, owner), "holdings": holdings(db, ph, owner), "company": company_view(db, ph, owner),
            "loan": loan_view(db, ph, owner), "taxes": taxes.view(db, ph),
            "retail": retail.snapshot(db, ph, clk, quotes, labor.get("scale", 1.0))}
