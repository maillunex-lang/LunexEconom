"""Initial city generation: real, city-owned houses around the crossroads in the centre of every city.

A city starts with a crossroads (roads.is_base_road). Houses are ordinary rows of `buildings` / `cells` (owner `town:<city id>`, kind `house`)
plus chunk events, so every client receives them like any other building. Every house gets its access road automatically, exactly as a player's
building does (roads.plan_access): the road cells are stored in `roads` and sent as `road_changed` events. Houses are NOT economic objects: no
`building_ops` row, no jobs, upkeep, taxes or wallets, and players cannot build or sell them.
A city has at least 16 houses: 10 of 1x1, 3 of 1x2 and 3 of 1x3 (PATTERN repeats for every further 16). Placement is deterministic for a given
database and running it twice never duplicates anything. Shared by SQLite and PostgreSQL (`ph` is the placeholder). See docs/CITYGEN.md.
"""
import hashlib
import json
import sys
from functools import lru_cache

import geo
import roads

CHUNK = 12
MAX_COORD = 10000
HOUSE_KIND = "house"
OWNER_PREFIX = "town:"
GAME_CITY = "ufa"                # the one city with a simulated economy: its houses follow the real population
HOUSE_CAPACITY = 8               # residents per house of the game city
MIN_HOUSES = 16                  # every city, 10 + 3 + 3
GROW_PER_MONTH = 6               # houses added per game month at most
OTHER_CITY_MAX = 30
RADIUS_USE = 0.9                 # houses stay inside this share of the city radius
MIN_DISTANCE = 2                 # nearest house centre to the crossroads (the arms of the cross are free)
MAX_ACCESS = 8                   # an access road longer than this is not built: the house goes elsewhere
# one block of 16 houses (w, h): 10 x 1x1, 3 x 1x2, 3 x 1x3, mixed so that every prefix looks like a street of different houses
PATTERN = ((1, 1), (1, 2), (1, 1), (1, 3), (1, 1), (1, 1), (1, 2), (1, 1), (1, 3), (1, 1), (1, 1), (1, 2), (1, 1), (1, 3), (1, 1), (1, 1))

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS geo_seed(city_id TEXT PRIMARY KEY, houses BIGINT NOT NULL, version INTEGER NOT NULL, updated BIGINT NOT NULL)",
)
VERSION = 2


def _q(sql, ph):
    return sql.replace("%s", ph)


def ensure(db, ph):
    for statement in SCHEMA:
        db.execute(statement)
    import zoning
    zoning.ensure(db, ph)


def owner_of(city_id):
    return OWNER_PREFIX + city_id


def terrain(x, y):
    """'road' | 'water' | 'tree' | 'grass' exactly as the client and roads.py decide it."""
    if roads.is_base_road(x, y):
        return "road"
    if roads.is_water(x, y):
        return "water"
    return "tree" if roads.terrain_noise(x, y) < 24 else "grass"


def shape_of(index):
    return PATTERN[index % len(PATTERN)]


# ---------- the candidates ----------
def _tie(city_id, x, y):
    return hashlib.sha1(("%s:%d:%d" % (city_id, x, y)).encode()).digest()[:4]


@lru_cache(maxsize=256)
def _candidates(city_id, w, h, level=0):
    """Lots (x0, y0) of a w x h house on free grass in the city zones (never the industrial zone), nearest to the crossroads first.
    `level`: growth level of the city (zoning.py), the radius grows with it."""
    city = geo.get_city(city_id)
    if city is None:
        raise ValueError("unknown city")
    import zoning
    cx, cy, radius = city["x"], city["y"], zoning.effective_radius(city["radius"], level)
    out = []
    for x0 in range(cx - radius, cx + radius + 1):
        for y0 in range(cy - radius, cy + radius + 1):
            mx, my = x0 + w / 2.0, y0 + h / 2.0
            distance = ((mx - cx) ** 2 + (my - cy) ** 2) ** 0.5
            if distance > radius * RADIUS_USE or distance < MIN_DISTANCE:
                continue
            if any(terrain(x0 + i, y0 + j) != "grass" for i in range(w) for j in range(h)):
                continue
            if any(zoning.zone_of(city_id, cx, cy, city["radius"], level, x0 + i, y0 + j) not in zoning.CITY_ZONES for i in range(w) for j in range(h)):
                continue
            out.append((distance, _tie(city_id, x0, y0), x0, y0))
    out.sort()
    return tuple((x0, y0) for _, _, x0, y0 in out)


def plan(city_id):
    """Possible lots for the smallest house (an upper bound of what fits), nearest to the centre first."""
    return list(_candidates(city_id, 1, 1))


def house_id(city_id, x, y):
    return hashlib.sha1(("town:%s:%d:%d" % (city_id, x, y)).encode()).hexdigest()[:32]


# ---------- targets ----------
def economic_population(db, ph):
    row = db.execute("SELECT next_population FROM population ORDER BY month_index DESC LIMIT 1").fetchone()
    return int(row[0]) if row else 200


def target_houses(city, population=None):
    if city["id"] == GAME_CITY:
        return max(MIN_HOUSES, int(population if population is not None else 200) // HOUSE_CAPACITY)
    return max(MIN_HOUSES, min(OTHER_CITY_MAX, city["radius"] // 2))


# ---------- writing ----------
def _count(db, ph, city_id):
    return int(db.execute(_q("SELECT COUNT(*) FROM buildings WHERE owner=%s AND kind=%s", ph), (owner_of(city_id), HOUSE_KIND)).fetchone()[0])


def _world_state(db, ph, city):
    """Occupied cells and dynamic roads around the city (access roads may run a little outside its radius)."""
    r = int(city["radius"] * 2.6) + MAX_ACCESS + 4          # room for the highest growth level
    box = (city["x"] - r, city["x"] + r, city["y"] - r, city["y"] + r)
    occupied = {(x, y) for x, y in db.execute(_q("SELECT x,y FROM cells WHERE x BETWEEN %s AND %s AND y BETWEEN %s AND %s", ph), box).fetchall()}
    dynamic = {(x, y) for x, y in db.execute(_q("SELECT x,y FROM roads WHERE x BETWEEN %s AND %s AND y BETWEEN %s AND %s", ph), box).fetchall()}
    return occupied, dynamic


def _emit(db, ph, kind, cells, payload_base):
    grouped = {}
    for a, b in cells:
        grouped.setdefault((a // CHUNK, b // CHUNK), []).append([a, b])
    for (cx, cy), coords in sorted(grouped.items()):
        db.execute(_q("INSERT INTO chunks(cx,cy,version) VALUES(%s,%s,1) ON CONFLICT(cx,cy) DO UPDATE SET version=chunks.version+1", ph), (cx, cy))
        version = db.execute(_q("SELECT version FROM chunks WHERE cx=%s AND cy=%s", ph), (cx, cy)).fetchone()[0]
        db.execute(_q("INSERT INTO events(cx,cy,version,kind,payload) VALUES(%s,%s,%s,%s,%s)", ph),
                   (cx, cy, version, kind, json.dumps(dict(payload_base, cells=coords))))


def _create_house(db, ph, city_id, x, y, w, h, road_cells, now):
    object_id = house_id(city_id, x, y)
    owner = owner_of(city_id)
    footprint = [(x + i, y + j) for i in range(w) for j in range(h)]
    db.execute(_q("INSERT INTO buildings(id,owner,kind,x,y,created) VALUES(%s,%s,%s,%s,%s,%s)", ph), (object_id, owner, HOUSE_KIND, x, y, now))
    for a, b in footprint:          # a loop, not executemany: a psycopg connection has no executemany
        db.execute(_q("INSERT INTO cells(x,y,object_id) VALUES(%s,%s,%s)", ph), (a, b, object_id))
    for a, b in road_cells:
        db.execute(_q("INSERT INTO roads(x,y,owner,created) VALUES(%s,%s,%s,%s)", ph), (a, b, owner, now))
    _emit(db, ph, "building_created", footprint, {"object_id": object_id, "owner": owner, "building_kind": HOUSE_KIND})
    _emit(db, ph, "road_changed", road_cells, {"object_id": object_id, "owner": owner})
    return object_id


def _remember(db, ph, city_id, now):
    db.execute(_q("DELETE FROM geo_seed WHERE city_id=%s", ph), (city_id,))
    db.execute(_q("INSERT INTO geo_seed(city_id,houses,version,updated) VALUES(%s,%s,%s,%s)", ph), (city_id, _count(db, ph, city_id), VERSION, now))


def seed_city(db, ph, city_id, now, population=None, max_new=None, dry_run=False):
    """Bring a city up to its target number of houses. Idempotent: existing houses count and occupied lots are skipped."""
    city = geo.get_city(city_id)
    if city is None:
        raise ValueError("unknown city")
    target = target_houses(city, population)
    have = _count(db, ph, city_id)
    result = {"city_id": city_id, "name": city["name"], "target": target, "existing": have, "plan_size": len(plan(city_id)), "placed": 0, "road_cells": 0,
              "mix": {}}
    need = max(0, target - have)
    if max_new is not None:
        need = min(need, max_new)
    if need == 0:
        return result
    import zoning
    level = zoning.levels(db, ph).get(city_id, 0)
    occupied, dynamic = _world_state(db, ph, city)
    import terrain_rules
    rad = city["radius"] + 128
    override_map = terrain_rules.preload(db, ph, (city["x"]-rad,city["x"]+rad,city["y"]-rad,city["y"]+rad))
    cx, cy = city["x"], city["y"]
    index = have
    failures = 0
    while result["placed"] < need and failures < 3:
        w0, h0 = shape_of(index)
        found = None
        for w, h in ([(w0, h0)] if w0 == h0 else [(w0, h0), (h0, w0)]):
            for x0, y0 in _candidates(city_id, w, h, level):
                cells = [(x0 + i, y0 + j) for i in range(w) for j in range(h)]
                if any(c in occupied or c in dynamic or terrain_rules.manual(*c, override_map) or terrain_rules.is_water(*c, override_map) for c in cells):
                    continue
                error, path = roads.plan_access(cells, dynamic, occupied, MAX_COORD, override_map)
                if error or len(path) > MAX_ACCESS:
                    continue
                distance = ((x0 + w / 2.0 - cx) ** 2 + (y0 + h / 2.0 - cy) ** 2) ** 0.5
                if found is None or distance < found[0] - 1e-9:
                    found = (distance, x0, y0, w, h, cells, path)
                break                                   # candidates are sorted: the first fitting lot of this orientation is its nearest
        if found is None:
            failures += 1
            index += 1                                  # nothing fits for this shape: try the next shape of the pattern
            continue
        _, x0, y0, w, h, cells, path = found
        new_roads = [c for c in path if not roads.is_base_road(*c) and c not in dynamic]
        if not dry_run:
            _create_house(db, ph, city_id, x0, y0, w, h, new_roads, now)
        occupied |= set(cells)
        dynamic |= set(new_roads)
        result["placed"] += 1
        result["road_cells"] += len(new_roads)
        key = "%dx%d" % (min(w, h), max(w, h))
        result["mix"][key] = result["mix"].get(key, 0) + 1
        index += 1
        failures = 0
    if not dry_run:
        _remember(db, ph, city_id, now)
    return result


# ---------- the first generation starts the world from a clean slate ----------
KEEP_TABLES = {"users", "sessions", "auth_attempts", "auth_tokens", "email_verified", "schema_migrations", "geo_seed"}    # accounts and operator data
DELETE_FIRST = ("cells", "building_ops")                 # rows that point at buildings


class WipeRequired(Exception):
    """The first generation would erase a world that already has players' data; the operator must confirm."""

    def __init__(self, counts):
        super().__init__("the first generation erases the game world")
        self.counts = counts


def _tables(db, ph):
    if ph == "?":
        rows = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    else:
        rows = db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()
    return [r[0] for r in rows]


def _wiped(name):
    return name not in KEEP_TABLES and not name.startswith("adm_")


def is_first_generation(db, ph):
    return int(db.execute("SELECT COUNT(*) FROM geo_seed").fetchone()[0]) == 0


def world_counts(db, ph):
    """What a wipe would erase (zero everywhere means an empty world: nothing to confirm)."""
    out = {}
    for table in ("buildings", "wallets", "roads", "trade_contracts", "loans"):
        if table in _tables(db, ph):
            out[table] = int(db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0])
    return out


def wipe_world(db, ph):
    """Erase the whole game world (buildings, roads, money, markets, companies, social data, clock). Accounts, sessions, operator data stay.
    Chunk versions are bumped and event numbers keep counting up, so connected clients reload the empty world instead of showing stale cells."""
    names = [n for n in _tables(db, ph) if _wiped(n)]
    ordered = [n for n in DELETE_FIRST if n in names] + [n for n in names if n not in DELETE_FIRST and n not in ("chunks", "world_clock")]
    if ph == "?":
        db.execute("PRAGMA defer_foreign_keys=ON")        # checked at commit, when everything is gone
        for name in ordered:
            db.execute("DELETE FROM " + name)             # AUTOINCREMENT counters (event numbers) are kept
    else:
        plain = [n for n in ordered if n != "events"]
        if "events" in ordered:
            db.execute("DELETE FROM events")              # not TRUNCATE ... RESTART: event numbers keep counting up
        if plain:
            db.execute("TRUNCATE TABLE " + ",".join(sorted(plain)) + " CASCADE")
    if "chunks" in names:
        db.execute("UPDATE chunks SET version=version+1")
    if "world_clock" in names:
        db.execute("DELETE FROM world_clock")            # the calendar restarts at the first call (month 0)
    return len(ordered)


def seed(db, ph, city_ids, now, dry_run=False, wipe=False):
    """`city_ids`: list of ids or the string 'all'. Returns one summary per city.

    The very first generation (nothing seeded yet) starts the world from a clean slate: with `wipe=True` the game world is erased first
    (accounts stay). If the world holds data and `wipe` is not set, WipeRequired is raised and nothing is written. A dry run never writes.
    """
    ids = [c["id"] for c in geo.cities()] if city_ids == "all" else list(city_ids)
    if not dry_run and is_first_generation(db, ph):
        counts = world_counts(db, ph)
        if any(counts.values()):
            if not wipe:
                raise WipeRequired(counts)
            wipe_world(db, ph)
    population = economic_population(db, ph)
    return [seed_city(db, ph, cid, now, population=population, dry_run=dry_run) for cid in ids]


def grow(db, ph, population, now):
    """Monthly hook of the economy: once the game city has been generated, new residents get new houses (a few per month)."""
    if db.execute(_q("SELECT 1 FROM geo_seed WHERE city_id=%s", ph), (GAME_CITY,)).fetchone() is None:
        return 0
    return seed_city(db, ph, GAME_CITY, now, population=population, max_new=GROW_PER_MONTH)["placed"]


def status(db, ph):
    population = economic_population(db, ph)
    seeded = {r[0]: (int(r[1]), int(r[2])) for r in db.execute("SELECT city_id,houses,version FROM geo_seed").fetchall()}
    out = []
    for city in geo.cities():
        out.append({"city_id": city["id"], "name": city["name"], "radius": city["radius"], "houses": _count(db, ph, city["id"]),
                    "target": target_houses(city, population), "plan_size": len(plan(city["id"])), "seeded": city["id"] in seeded})
    return out


# ---------- command line (run on the server by the operator) ----------
def _main(argv):
    import time
    apply = "--apply" in argv
    args = [a for a in argv if a not in ("--apply", "--wipe")]
    command = args[0] if args else "status"
    which = "all" if "--all" in args else ([args[args.index("--city") + 1]] if "--city" in args else None)
    import os
    if os.environ.get("LUNEX_DB_ENGINE") == "postgres":
        import postgres_db
        connection, ph = postgres_db.connect(), "%s"
        connection.execute("SELECT pg_advisory_xact_lock(20261114)")
    else:
        import game_server
        connection, ph = game_server.connect(), "?"
        connection.execute("BEGIN IMMEDIATE")
    with connection as db:
        ensure(db, ph)
        if command == "status":
            print(json.dumps(status(db, ph), ensure_ascii=False, indent=1))
        elif command == "seed" and which is not None:
            first = is_first_generation(db, ph)
            if first:
                print("FIRST GENERATION: the game world will be ERASED first (accounts stay). Currently: %s" % json.dumps(world_counts(db, ph)))
            try:
                print(json.dumps(seed(db, ph, which, int(time.time()), dry_run=not apply, wipe="--wipe" in argv), ensure_ascii=False, indent=1))
            except WipeRequired as error:
                print("REFUSED: the world holds data %s. Make a backup, then repeat with --apply --wipe" % json.dumps(error.counts), file=sys.stderr)
                return 3
            print("APPLIED" if apply else "DRY RUN: nothing was written (add --apply)")
            if apply:
                db.commit()
        else:
            print("usage: citygen.py status | seed (--all | --city ID) [--apply]", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))