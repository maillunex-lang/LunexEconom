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


@lru_cache(maxsize=64)
def _candidates(city_id, w, h):
    """Lots (x0, y0) of a w x h house on free grass, nearest to the crossroads first."""
    city = geo.get_city(city_id)
    if city is None:
        raise ValueError("unknown city")
    cx, cy, radius = city["x"], city["y"], city["radius"]
    out = []
    for x0 in range(cx - radius, cx + radius + 1):
        for y0 in range(cy - radius, cy + radius + 1):
            mx, my = x0 + w / 2.0, y0 + h / 2.0
            distance = ((mx - cx) ** 2 + (my - cy) ** 2) ** 0.5
            if distance > radius * RADIUS_USE or distance < MIN_DISTANCE:
                continue
            if any(terrain(x0 + i, y0 + j) != "grass" for i in range(w) for j in range(h)):
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
    r = city["radius"] + MAX_ACCESS + 4
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
    occupied, dynamic = _world_state(db, ph, city)
    cx, cy = city["x"], city["y"]
    index = have
    failures = 0
    while result["placed"] < need and failures < 3:
        w0, h0 = shape_of(index)
        found = None
        for w, h in ([(w0, h0)] if w0 == h0 else [(w0, h0), (h0, w0)]):
            for x0, y0 in _candidates(city_id, w, h):
                cells = [(x0 + i, y0 + j) for i in range(w) for j in range(h)]
                if any(c in occupied or c in dynamic for c in cells):
                    continue
                error, path = roads.plan_access(cells, dynamic, occupied, MAX_COORD)
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


def seed(db, ph, city_ids, now, dry_run=False):
    """`city_ids`: list of ids or the string 'all'. Returns one summary per city."""
    ids = [c["id"] for c in geo.cities()] if city_ids == "all" else list(city_ids)
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
    args = [a for a in argv if a != "--apply"]
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
            print(json.dumps(seed(db, ph, which, int(time.time()), dry_run=not apply), ensure_ascii=False, indent=1))
            print("APPLIED" if apply else "DRY RUN: nothing was written (add --apply)")
            if apply:
                db.commit()
        else:
            print("usage: citygen.py status | seed (--all | --city ID) [--apply]", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
