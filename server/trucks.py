"""Company lorry fleet (EX-06).

Without a fleet, inter-city freight stays the old per-kilometre tariff from
``regions.unit_cost`` so an existing world does not change. A company that owns
lorries ships only what free lorries can carry; the rest stays in the origin
city and is sold there. ``regions.py`` itself is not modified: ``trade_shipments.unit_cost``
is still the catalog tariff, while the cash freight is the figure returned here.
"""
import json
import uuid

import balance as balance_registry
import economy
import regions

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS company_trucks(owner TEXT PRIMARY KEY, units INTEGER NOT NULL, capacity_each INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS truck_trips(id TEXT PRIMARY KEY, owner TEXT NOT NULL, origin TEXT NOT NULL, destination TEXT NOT NULL, "
    "product TEXT NOT NULL, qty BIGINT NOT NULL, trucks INTEGER NOT NULL, depart_month BIGINT NOT NULL, arrive_month BIGINT NOT NULL, status TEXT NOT NULL)",
)


def _q(sql, ph):
    return sql.replace("%s", ph)


def release_arrived(db, ph, month):
    db.execute(_q("UPDATE truck_trips SET status='delivered' WHERE status='transit' AND arrive_month<=%s", ph), (month,))


def fleet(db, ph, owner):
    row = db.execute(_q("SELECT units, capacity_each FROM company_trucks WHERE owner=%s", ph), (owner,)).fetchone()
    if not row:
        return 0, int(balance_registry.get("TRUCK_CAPACITY"))
    return int(row[0]), int(row[1])


def free_trucks(db, ph, owner, month):
    units, _cap = fleet(db, ph, owner)
    if units <= 0:
        return 0
    busy = db.execute(_q(
        "SELECT COALESCE(SUM(trucks),0) FROM truck_trips WHERE owner=%s AND status='transit' AND arrive_month>%s", ph),
        (owner, month)).fetchone()
    return max(0, units - int(busy[0] or 0))


def take(db, ph, owner, product, origin, destination, qty, month):
    """Return ``(ship_qty, freight_roubles)``. No fleet → ship all at the legacy tariff."""
    qty = int(qty)
    if qty <= 0:
        return 0, 0
    legacy = qty * int(regions.unit_cost(product, origin, destination))
    units, cap = fleet(db, ph, owner)
    if units <= 0:
        return qty, legacy
    free = free_trucks(db, ph, owner, month)
    if free <= 0:
        return 0, 0
    ship = min(qty, free * cap)
    need = max(1, (ship + cap - 1) // cap)
    km = regions.road_km(origin, destination)
    per = max(1, int(round(km * float(balance_registry.get("TRUCK_COST_PER_KM")))))
    arrive = int(month) + max(int(regions.transit_months(origin, destination)), 1)
    db.execute(_q(
        "INSERT INTO truck_trips(id,owner,origin,destination,product,qty,trucks,depart_month,arrive_month,status) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", ph),
        (uuid.uuid4().hex, owner, origin, destination, product, ship, need, int(month), arrive, "transit"))
    return ship, need * per


def add_upkeep(db, ph, companies):
    """Add lorry upkeep to companies that already have a monthly bill. No lorries → no change."""
    upkeep = int(balance_registry.get("TRUCK_UPKEEP"))
    if upkeep <= 0:
        return
    for owner, units in db.execute("SELECT owner, units FROM company_trucks WHERE units>0").fetchall():
        company = companies.get(owner)
        if company is not None:
            company["maint"] += int(units) * upkeep


def buy(db, ph, owner, payload, now, month=None):
    count = payload.get("count", 1)
    request_id = payload.get("request_id")
    try:
        uuid.UUID(str(request_id))
    except (ValueError, TypeError, AttributeError):
        return 400, {"error": "invalid_request_id"}
    if type(count) is not int or not 1 <= count <= 20:
        return 400, {"error": "invalid_truck_count"}
    prev = db.execute(_q("SELECT response FROM commands WHERE owner=%s AND request_id=%s", ph), (owner, request_id)).fetchone()
    if prev:
        return 200, json.loads(prev[0])
    price = int(balance_registry.get("TRUCK_PRICE"))
    cap = int(balance_registry.get("TRUCK_CAPACITY"))
    cost = price * count
    current = economy.ensure_wallet(db, ph, owner, now)
    if current < cost:
        return 402, {"error": "insufficient_funds", "cost": cost, "balance": current}
    economy.post(db, ph, "trucks", "Покупка грузовиков: %d" % count,
                 [(economy.player_account(owner), -cost), ("system:logistics", cost)], now)
    row = db.execute(_q("SELECT units FROM company_trucks WHERE owner=%s", ph), (owner,)).fetchone()
    if row:
        db.execute(_q("UPDATE company_trucks SET units=units+%s WHERE owner=%s", ph), (count, owner))
        owned = int(row[0]) + count
    else:
        db.execute(_q("INSERT INTO company_trucks(owner,units,capacity_each) VALUES(%s,%s,%s)", ph), (owner, count, cap))
        owned = count
    result = {"ok": True, "units": owned, "capacity_each": cap, "cost": cost, "balance": current - cost}
    db.execute(_q("INSERT INTO commands(owner,request_id,response) VALUES(%s,%s,%s)", ph),
               (owner, request_id, json.dumps(result, ensure_ascii=False)))
    return 201, result


def view(db, ph, owner):
    units, cap = fleet(db, ph, owner)
    rows = db.execute(_q(
        "SELECT id,origin,destination,product,qty,trucks,depart_month,arrive_month,status FROM truck_trips "
        "WHERE owner=%s ORDER BY depart_month,id", ph), (owner,)).fetchall()
    return {
        "units": units, "capacity_each": cap, "capacity": units * cap,
        "upkeep": units * int(balance_registry.get("TRUCK_UPKEEP")),
        "price": int(balance_registry.get("TRUCK_PRICE")),
        "legacy_tariff_without_fleet": True,
        "trips": [{"id": i, "origin": o, "destination": d, "product": p, "qty": int(q), "trucks": int(t),
                   "depart_month": int(dm), "arrive_month": int(am), "status": st}
                  for i, o, d, p, q, t, dm, am, st in rows],
    }
