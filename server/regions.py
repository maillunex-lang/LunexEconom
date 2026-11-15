"""City economies: every city is a region with its own population, labour market, prices and local supply and demand.

A building belongs to the region of the NEAREST city. A region takes part in the economy only when it is *active*: the game city (Ufa) is
always active, any other city becomes active when a company has a building there or when its initial generation has been run
(docs/CITYGEN.md). With only Ufa active the economy is exactly the single market it was before.

Goods move between regions only through the shared market, by shipments with a delivery time that grows with the road distance
(docs/CITY_ECONOMY.md). The constants below are the tuning knobs. Shared by SQLite and PostgreSQL (`ph` is the SQL placeholder).
"""
import heapq
import math
from functools import lru_cache

import economy
import geo

HOME = "ufa"                    # the game city: legacy `population` table, mayor, social buildings
SPEED_KMH = 85                  # a lorry on the road: 500 km is about 6 hours, like in real life
MONTH_HOURS = 720               # a game month is 30 days; trips shorter than that are delivered within the month
TRANSPORT_COST_PER_KM = 0.0006  # of the reference price per unit per road km (175 km is about 10 %)
MIN_MARGIN_RATIO = 0.04         # a lane is used only if the price gap beats the transport cost by this share of the reference price
SURPLUS_SHARE = 1.0             # share of a region's genuine surplus (supply beyond its own demand) that may be shipped out
POPULATION_EXPONENT = 0.5       # game population of a city ~ BASE_POPULATION * (real population / Ufa) ** exponent
MIN_POPULATION_FOR_CITY = 60

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS region_population(region TEXT NOT NULL, month_index BIGINT NOT NULL, population BIGINT NOT NULL, labor_force BIGINT NOT NULL, "
    "jobs BIGINT NOT NULL, wage BIGINT NOT NULL, staffing_permille INTEGER NOT NULL, demand_permille INTEGER NOT NULL, next_population BIGINT NOT NULL, "
    "PRIMARY KEY(region, month_index))",
    "CREATE TABLE IF NOT EXISTS market_prices_region(region TEXT NOT NULL, product TEXT NOT NULL, month_index BIGINT NOT NULL, price BIGINT NOT NULL, "
    "supply BIGINT NOT NULL, demand BIGINT NOT NULL, imports BIGINT NOT NULL, exports BIGINT NOT NULL, PRIMARY KEY(region, product, month_index))",
    "CREATE TABLE IF NOT EXISTS trade_shipments(id TEXT PRIMARY KEY, product TEXT NOT NULL, origin TEXT NOT NULL, destination TEXT NOT NULL, qty BIGINT NOT NULL, "
    "unit_cost BIGINT NOT NULL, depart_month BIGINT NOT NULL, arrive_month BIGINT NOT NULL, status TEXT NOT NULL)",
)


def _q(sql, ph):
    return sql.replace("%s", ph)


def ensure(db, ph):
    for statement in SCHEMA:
        db.execute(statement)


# ---------- geography ----------
@lru_cache(maxsize=1)
def _centers():
    return tuple((c["id"], c["x"], c["y"]) for c in geo.cities())


@lru_cache(maxsize=1)
def region_ids():
    return tuple(cid for cid, _, _ in _centers())


@lru_cache(maxsize=1)
def _names():
    return {c["id"]: c["name"] for c in geo.cities()}


def name(region):
    return _names().get(region, region)


def region_of(x, y):
    """The nearest city centre (ties: the earlier city in the list; the game city comes first)."""
    best, best_d = HOME, None
    for cid, cx, cy in _centers():
        d = (x - cx) ** 2 + (y - cy) ** 2
        if best_d is None or d < best_d:
            best, best_d = cid, d
    return best


@lru_cache(maxsize=1)
def _road_matrix():
    adjacency = {}
    for route in geo.routes():
        adjacency.setdefault(route["from"], []).append((route["to"], route["road_km"]))
        adjacency.setdefault(route["to"], []).append((route["from"], route["road_km"]))
    matrix = {}
    for source in region_ids():
        dist = {source: 0.0}
        heap = [(0.0, source)]
        while heap:
            d, u = heapq.heappop(heap)
            if d > dist[u]:
                continue
            for v, w in adjacency.get(u, ()):
                if d + w < dist.get(v, 1e18):
                    dist[v] = d + w
                    heapq.heappush(heap, (d + w, v))
        matrix[source] = dist
    return matrix


def road_km(a, b):
    if a == b:
        return 0.0
    return float(_road_matrix()[a][b])


def transit_hours(a, b):
    """Hours on the road, as in real life (500 km is about 6 hours); 0 inside one city. Grows with the road distance."""
    if a == b:
        return 0
    return max(1, int(math.ceil(road_km(a, b) / SPEED_KMH)))


def transit_months(a, b):
    """Whole game months of delay. The economy settles once a month, so a trip of hours lands within the same month (0);
    only a trip longer than a month (not possible on this map, kept for a bigger world) is delayed to a later settlement."""
    return transit_hours(a, b) // MONTH_HOURS


def unit_cost(product, a, b):
    """Transport cost of one unit between two cities, in roubles."""
    ref = economy.market_of(product)["reference_price"]
    return int(round(ref * TRANSPORT_COST_PER_KM * road_km(a, b)))


@lru_cache(maxsize=1)
def _estimates():
    return {c["id"]: c["population_estimate"] for c in geo.cities()}


def base_population(region):
    """Starting residents of a city's economy (the game city keeps the legacy value)."""
    if region == HOME:
        return economy.BASE_POPULATION
    share = _estimates()[region] / float(_estimates()[HOME])
    return max(MIN_POPULATION_FOR_CITY, int(round(economy.BASE_POPULATION * share ** POPULATION_EXPONENT)))


# ---------- which cities take part ----------
def building_regions(db, ph):
    """{object_id: region} for every operating building (a building without coordinates counts as the game city)."""
    out = {}
    for object_id, x, y in db.execute("SELECT o.object_id,b.x,b.y FROM building_ops o LEFT JOIN buildings b ON b.id=o.object_id").fetchall():
        out[object_id] = HOME if x is None else region_of(int(x), int(y))
    return out


def active_regions(db, ph):
    """The game city, every city that has a company building and every generated city (docs/CITYGEN.md)."""
    active = {HOME}
    active |= set(building_regions(db, ph).values())
    try:
        active |= {r[0] for r in db.execute("SELECT city_id FROM geo_seed").fetchall() if r[0] in set(region_ids())}
    except Exception:           # no generation table in a bare database
        pass
    return sorted(active, key=region_ids().index)


def home_region(db, ph, owner):
    """The region where the owner has most jobs (ties: the earlier city); the game city for an owner without buildings."""
    jobs = {}
    rows = db.execute(_q("SELECT o.kind,b.x,b.y FROM building_ops o LEFT JOIN buildings b ON b.id=o.object_id WHERE o.owner=%s", ph), (owner,)).fetchall()
    for kind, x, y in rows:
        region = HOME if x is None else region_of(int(x), int(y))
        jobs[region] = jobs.get(region, 0) + economy.kind_jobs(kind) + 1
    if not jobs:
        return HOME
    return sorted(jobs, key=lambda r: (-jobs[r], region_ids().index(r)))[0]


# ---------- population of the other cities ----------
def population_at(db, ph, region, month):
    """Residents at the start of `month`: the previous month's result, or the starting population of a city that just became active."""
    row = db.execute(_q("SELECT next_population FROM region_population WHERE region=%s AND month_index=%s", ph), (region, month - 1)).fetchone()
    if row is None:
        row = db.execute(_q("SELECT next_population FROM region_population WHERE region=%s ORDER BY month_index DESC LIMIT 1", ph), (region,)).fetchone()
    return int(row[0]) if row else base_population(region)


def save_population(db, ph, region, month, lab, staffing, next_pop):
    db.execute(_q("INSERT INTO region_population(region,month_index,population,labor_force,jobs,wage,staffing_permille,demand_permille,next_population) "
                  "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(region,month_index) DO NOTHING", ph),
               (region, month, lab["population"], lab["labor_force"], lab["jobs"], lab["wage"], int(staffing * 1000), int(lab["scale"] * 1000), next_pop))


def previous_price(db, ph, region, product, month):
    row = db.execute(_q("SELECT price FROM market_prices_region WHERE region=%s AND product=%s AND month_index=%s", ph), (region, product, month - 1)).fetchone()
    return int(row[0]) if row else None


def price_history(db, ph, region, product, month, count):
    rows = []
    for i in range(count):
        row = db.execute(_q("SELECT price FROM market_prices_region WHERE region=%s AND product=%s AND month_index=%s", ph), (region, product, month - 1 - i)).fetchone()
        if row:
            rows.append(int(row[0]))
    return rows


# ---------- shipments ----------
def pipeline(db, ph, product):
    """{destination: units still in transit}."""
    out = {}
    for destination, qty in db.execute(_q("SELECT destination,qty FROM trade_shipments WHERE product=%s AND status='transit'", ph), (product,)).fetchall():
        out[destination] = out.get(destination, 0) + int(qty)
    return out


def arrivals(db, ph, product, month):
    """Mark the shipments that arrive this month as delivered and return {destination: units}."""
    out = {}
    rows = db.execute(_q("SELECT id,destination,qty FROM trade_shipments WHERE product=%s AND status='transit' AND arrive_month<=%s", ph), (product, month)).fetchall()
    for shipment_id, destination, qty in rows:
        out[destination] = out.get(destination, 0) + int(qty)
        db.execute(_q("UPDATE trade_shipments SET status='delivered' WHERE id=%s", ph), (shipment_id,))
    return out


def dispatch(db, ph, product, origin, destination, qty, month, shipment_id):
    """Record a shipment. Returns True when it arrives within the same month (the normal case): the caller adds it to the destination's supply."""
    arrive = month + transit_months(origin, destination)
    db.execute(_q("INSERT INTO trade_shipments(id,product,origin,destination,qty,unit_cost,depart_month,arrive_month,status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)", ph),
               (shipment_id, product, origin, destination, int(qty), unit_cost(product, origin, destination), month, arrive, "delivered" if arrive <= month else "transit"))
    return arrive <= month


def plan_exports(product, regions, offers, local_demand, arriving, previous, in_transit):
    """Which surplus goes where this month. Pure function (tested on its own).

    offers/local_demand/arriving/previous/in_transit are dicts by region. A region ships out only its genuine surplus (what it supplies
    beyond its own demand); a lane is used only when the destination's price beats the origin's by more than the transport cost,
    and never more than the destination still lacks after counting what is already on the road to it. Returns [(origin, destination, qty)].
    """
    ref = economy.market_of(product)["reference_price"]
    surplus = {r: int(max(0, offers.get(r, 0) + arriving.get(r, 0) - local_demand.get(r, 0)) * SURPLUS_SHARE) for r in regions}
    lacking = {r: max(0, local_demand.get(r, 0) - offers.get(r, 0) - arriving.get(r, 0) - in_transit.get(r, 0)) for r in regions}
    lanes = []
    for a in regions:
        for b in regions:
            if a == b:
                continue
            margin = previous.get(b, ref) - previous.get(a, ref) - unit_cost(product, a, b)
            if margin > MIN_MARGIN_RATIO * ref:
                lanes.append((-margin, transit_hours(a, b), a, b))
    plan = []
    for _, _, a, b in sorted(lanes):
        qty = min(surplus[a], lacking[b])
        if qty > 0:
            plan.append((a, b, qty))
            surplus[a] -= qty
            lacking[b] -= qty
    return plan


# ---------- API view ----------
def overview(db, ph):
    """GET /economy/regions: every active city with its latest population, prices and goods on the road (public, like /geo)."""
    active = active_regions(db, ph)
    rows = db.execute("SELECT MAX(month_index) FROM market_prices_region").fetchone()
    month = int(rows[0]) if rows and rows[0] is not None else None
    cities = []
    for region in active:
        pop = db.execute(_q("SELECT population,labor_force,jobs,wage,staffing_permille,month_index FROM region_population WHERE region=%s ORDER BY month_index DESC LIMIT 1", ph),
                         (region,)).fetchone()
        if region == HOME:
            pop = db.execute("SELECT population,labor_force,jobs,wage,staffing_permille,month_index FROM population ORDER BY month_index DESC LIMIT 1").fetchone()
        prices = {}
        if month is not None:
            for product, price, supply, demand, imports, exports in db.execute(_q(
                    "SELECT product,price,supply,demand,imports,exports FROM market_prices_region WHERE region=%s AND month_index=%s", ph), (region, month)).fetchall():
                prices[product] = {"price": int(price), "supply": int(supply), "demand": int(demand), "imports": int(imports), "exports": int(exports)}
        cities.append({"id": region, "name": name(region), "population": int(pop[0]) if pop else base_population(region),
                       "labor_force": int(pop[1]) if pop else 0, "jobs": int(pop[2]) if pop else 0, "wage": int(pop[3]) if pop else economy.BASE_WAGE,
                       "staffing": (int(pop[4]) / 1000.0) if pop else 1.0, "prices": prices})
    shipments = [{"product": p, "origin": o, "destination": d, "qty": int(q), "depart_month": int(dm), "arrive_month": int(am)}
                 for p, o, d, q, dm, am in db.execute("SELECT product,origin,destination,qty,depart_month,arrive_month FROM trade_shipments WHERE status='transit' ORDER BY arrive_month,id").fetchall()]
    recent = []
    if month is not None:
        recent = [{"product": p, "origin": o, "destination": d, "qty": int(q), "hours": transit_hours(o, d)}
                  for p, o, d, q in db.execute(_q("SELECT product,origin,destination,qty FROM trade_shipments WHERE depart_month=%s ORDER BY id", ph), (month,)).fetchall()]
    lanes = [{"from": a, "to": b, "road_km": round(road_km(a, b)), "hours": transit_hours(a, b), "months": transit_months(a, b)} for a in active for b in active if a != b]
    return {"month": month, "speed_kmh": SPEED_KMH, "cities": cities, "shipments": shipments, "recent": recent, "lanes": lanes}
