"""City zones and dynamic city growth. Shared by SQLite and PostgreSQL (`ph` is the SQL placeholder). See docs/ZONING.md.

Every generated city has three kinds of land, computed from the city centre, its CURRENT radius and a fixed industrial direction:
  * city      - the centre (up to CORE_SHARE of the radius) and the suburb around it: houses, shops, schools, hospitals, parks;
  * industrial - a wedge of the outer ring (WEDGE_DEGREES wide, direction fixed per city): factories, warehouses, mines, farms;
  * open land  - everything beyond the radius: farms, mines, warehouses.
Factories can therefore never stand in a city centre. When a city fills up (EXPAND_FILL of its urban or industrial land is built over) its radius
grows by EXPAND_STEP of the original, so free land always remains. The rules apply once cities have been generated (docs/CITYGEN.md); before
that the empty world has no zones. The same geometry is mirrored in client/zones.gd (parity is tested).
"""
import hashlib
import math

import geo

CORE_SHARE = 0.40
WEDGE_DEGREES = 100.0
EXPAND_FILL = 0.40               # share of built-over land that makes a city grow
EXPAND_STEP = 0.25               # radius growth per level, share of the original radius
MAX_LEVEL = 6
FREE_LAND = 0.8                  # share of land that is not trees or river (area estimate)

CITY_ZONES = ("center", "suburb")
ALLOWED = {
    "house": ("center", "suburb"), "shop": ("center", "suburb"), "school": ("center", "suburb"), "hospital": ("center", "suburb"),
    "park": ("center", "suburb"),
    "factory": ("industrial",), "warehouse": ("industrial", "open"), "mine": ("industrial", "open"), "farm": ("industrial", "open"),
}
ZONE_NAMES = {"center": "центр города", "suburb": "жилой район", "industrial": "промзона", "open": "свободная земля"}

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS city_zones(city_id TEXT PRIMARY KEY, level INTEGER NOT NULL, updated BIGINT NOT NULL)",
)


def _q(sql, ph):
    return sql.replace("%s", ph)


def ensure(db, ph):
    for statement in SCHEMA:
        db.execute(statement)


def effective_radius(base_radius, level):
    return int(round(base_radius * (1.0 + EXPAND_STEP * level)))


def wedge_angle(city_id):
    """Direction (degrees, 0 = +x, counter-clockwise towards +y) of the industrial wedge of a city."""
    return int.from_bytes(hashlib.sha1(("zone:" + city_id).encode()).digest()[:2], "big") % 360


def zone_of(city_id, cx, cy, base_radius, level, x, y):
    """'center' | 'suburb' | 'industrial' | 'open' for a cell, relative to one city."""
    radius = effective_radius(base_radius, level)
    dx, dy = x - cx, y - cy
    distance = math.hypot(dx, dy)
    if distance > radius:
        return "open"
    if distance <= radius * CORE_SHARE:
        return "center"
    angle = math.degrees(math.atan2(dy, dx)) % 360.0
    diff = abs((angle - wedge_angle(city_id) + 180.0) % 360.0 - 180.0)
    return "industrial" if diff <= WEDGE_DEGREES / 2.0 else "suburb"


@__import__("functools").lru_cache(maxsize=1)
def _cities():
    return tuple((c["id"], c["x"], c["y"], c["radius"]) for c in geo.cities())


def levels(db, ph):
    return {r[0]: int(r[1]) for r in db.execute("SELECT city_id,level FROM city_zones").fetchall()}


def zone_at(x, y, level_of):
    """Zone of a cell: the nearest city decides. `level_of`: {city_id: level}."""
    best, best_d = None, None
    for cid, cx, cy, radius in _cities():
        d = (x - cx) ** 2 + (y - cy) ** 2
        if best_d is None or d < best_d:
            best, best_d = (cid, cx, cy, radius), d
    cid, cx, cy, radius = best
    return zone_of(cid, cx, cy, radius, level_of.get(cid, 0), x, y)


def enabled(db, ph):
    """Zones exist once the cities have been generated."""
    try:
        return db.execute("SELECT 1 FROM geo_seed LIMIT 1").fetchone() is not None
    except Exception:
        return False


def check(db, ph, kind, footprint):
    """None when a building of `kind` may stand on the footprint, else (zone, allowed zones) of the first offending cell."""
    allowed = ALLOWED.get(kind)
    if allowed is None or not enabled(db, ph):
        return None
    level_of = levels(db, ph)
    for x, y in footprint:
        zone = zone_at(x, y, level_of)
        if zone not in allowed:
            return zone, allowed
    return None


def error_body(found, kind):
    zone, allowed = found
    return {"error": "wrong_zone", "zone": zone, "zone_name": ZONE_NAMES[zone], "kind": kind,
            "allowed": [ZONE_NAMES[z] for z in allowed]}


# ---------- growth ----------
def _fill(db, ph, city_id, cx, cy, radius_now, level_now):
    """(urban fill, industrial fill): built-over share of the city land and of the industrial wedge."""
    base = geo.get_city(city_id)["radius"]
    r = effective_radius(base, level_now)
    box = (cx - r, cx + r, cy - r, cy + r)
    occupied = db.execute(_q("SELECT x,y FROM cells WHERE x BETWEEN %s AND %s AND y BETWEEN %s AND %s", ph), box).fetchall()
    roads_n = db.execute(_q("SELECT x,y FROM roads WHERE x BETWEEN %s AND %s AND y BETWEEN %s AND %s", ph), box).fetchall()
    urban = industrial = 0
    for x, y in list(occupied) + list(roads_n):
        zone = zone_of(city_id, cx, cy, base, level_now, int(x), int(y))
        if zone in CITY_ZONES:
            urban += 1
        elif zone == "industrial":
            industrial += 1
    wedge_share = WEDGE_DEGREES / 360.0
    area = math.pi * (r ** 2) * FREE_LAND
    ring = area * (1.0 - CORE_SHARE ** 2)
    urban_area = area * (CORE_SHARE ** 2) + ring * (1.0 - wedge_share)
    industrial_area = ring * wedge_share
    return urban / max(urban_area, 1.0), industrial / max(industrial_area, 1.0)


def expand_cities(db, ph, now):
    """Monthly: every generated city whose land is filling up grows by one level. Returns {city_id: new level}."""
    grown = {}
    seeded = {r[0] for r in db.execute("SELECT city_id FROM geo_seed").fetchall()}
    current = levels(db, ph)
    for cid, cx, cy, radius in _cities():
        if cid not in seeded:
            continue
        level = current.get(cid, 0)
        if level >= MAX_LEVEL:
            continue
        urban, industrial = _fill(db, ph, cid, cx, cy, radius, level)
        if urban >= EXPAND_FILL or industrial >= EXPAND_FILL:
            db.execute(_q("DELETE FROM city_zones WHERE city_id=%s", ph), (cid,))
            db.execute(_q("INSERT INTO city_zones(city_id,level,updated) VALUES(%s,%s,%s)", ph), (cid, level + 1, now))
            grown[cid] = level + 1
    return grown


def overview(db, ph):
    """GET /geo/zones: current geometry of every city's zones (the client draws and checks the same rules)."""
    on = enabled(db, ph)
    level_of = levels(db, ph) if on else {}
    out = []
    for c in geo.cities():
        level = level_of.get(c["id"], 0)
        r = effective_radius(c["radius"], level)
        out.append({"id": c["id"], "x": c["x"], "y": c["y"], "base_radius": c["radius"], "level": level, "radius": r,
                    "core": round(r * CORE_SHARE, 2), "wedge_angle": wedge_angle(c["id"]), "wedge_degrees": WEDGE_DEGREES})
    return {"enabled": on, "core_share": CORE_SHARE, "allowed": {k: list(v) for k, v in ALLOWED.items()}, "cities": out}
