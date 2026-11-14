"""Initial city generation: real, city-owned houses along the streets that the client already draws as the city background.

Houses are ordinary rows of `buildings` / `cells` (owner `town:<city id>`, kind `house`) plus chunk events, so every client receives them like any
other building. They are NOT economic objects: no `building_ops` row, no jobs, upkeep, taxes or wallets, and players cannot build or sell them.
Placement is a pure function of the city (deterministic, identical on every run); running it twice never duplicates anything.
The street/square/industrial predicates below mirror client/city_layout.gd cell for cell (parity is tested).
Shared by SQLite and PostgreSQL (`ph` is the placeholder). See docs/CITYGEN.md.
"""
import hashlib
import json
import sys
from functools import lru_cache

import geo
import roads

SEED = 18273
CHUNK = 12
HOUSE_KIND = "house"
HOUSE_SIZE = (2, 2)
OWNER_PREFIX = "town:"
GAME_CITY = "ufa"                # the one city with a simulated economy: its houses follow the real population
HOUSE_CAPACITY = 8               # residents per house of the game city
GAME_CITY_MIN_HOUSES = 12
GROW_PER_MONTH = 6               # houses added per game month at most
OTHER_CITY_MIN, OTHER_CITY_MAX = 8, 30
RADIUS_USE = 0.9                 # houses stay inside this share of the city radius
INNER_FREE_GAME_CITY = 9         # keep the start area of the game city free for players
INNER_FREE_OTHER = 3
INDUSTRIAL_WORDS = ("нефть", "металлургия", "добыча", "промышленность")

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS geo_seed(city_id TEXT PRIMARY KEY, houses BIGINT NOT NULL, version INTEGER NOT NULL, updated BIGINT NOT NULL)",
)
VERSION = 1


def _q(sql, ph):
    return sql.replace("%s", ph)


def ensure(db, ph):
    for statement in SCHEMA:
        db.execute(statement)


def owner_of(city_id):
    return OWNER_PREFIX + city_id


# ---------- mirror of client/city_layout.gd ----------
@lru_cache(maxsize=None)
def _city_seed(city_id):
    value = 2166136261
    for byte in city_id.encode("utf-8"):
        value = ((value ^ byte) * 16777619) & 0x7FFFFFFF
    return value


def _spacing(city, x, y):
    distance = ((x - city["x"]) ** 2 + (y - city["y"]) ** 2) ** 0.5
    return 7 if distance / float(city["radius"]) < 0.52 else 11


def is_street(city, x, y):
    radius = city["radius"]
    if radius < 1 or ((x - city["x"]) ** 2 + (y - city["y"]) ** 2) ** 0.5 > radius:
        return False
    seed = _city_seed(city["id"])
    spacing = _spacing(city, x, y)
    return (x + seed % 11) % spacing == 0 or (y + (seed // 13) % 11) % spacing == 0


def is_square(city, x, y):
    return abs(x - city["x"]) < 3 and abs(y - city["y"]) < 3


def _is_industrial_city(city):
    return any(word in city.get("specialization", "") for word in INDUSTRIAL_WORDS)


def in_industrial_band(city, x, y):
    if not _is_industrial_city(city):
        return False
    density = ((x - city["x"]) ** 2 + (y - city["y"]) ** 2) ** 0.5 / float(city["radius"])
    return 0.72 < density < 0.94


def terrain(x, y):
    """'road' | 'water' | 'tree' | 'grass' exactly as the client and roads.py decide it."""
    if roads.is_base_road(x, y):
        return "road"
    n = roads.terrain_noise(x, y)
    return "water" if n < 8 else ("tree" if n < 24 else "grass")


# ---------- the plan ----------
def _tie(city_id, x, y):
    return hashlib.sha1(("%s:%d:%d" % (city_id, x, y)).encode()).digest()[:4]


@lru_cache(maxsize=64)
def _plan(city_id):
    city = geo.get_city(city_id)
    if city is None:
        raise ValueError("unknown city")
    cx, cy, radius = city["x"], city["y"], city["radius"]
    inner = INNER_FREE_GAME_CITY if city_id == GAME_CITY else INNER_FREE_OTHER
    width, height = HOUSE_SIZE
    candidates = []
    for x0 in range(cx - radius, cx + radius + 1):
        for y0 in range(cy - radius, cy + radius + 1):
            mx, my = x0 + width / 2.0, y0 + height / 2.0
            distance = ((mx - cx) ** 2 + (my - cy) ** 2) ** 0.5
            if distance > radius * RADIUS_USE or distance < inner:
                continue
            cells = [(x0 + i, y0 + j) for i in range(width) for j in range(height)]
            if any(terrain(*c) != "grass" or is_street(city, *c) or is_square(city, *c) or in_industrial_band(city, *c) for c in cells):
                continue
            ring = [(x0 + i, y0 + j) for i in range(-1, width + 1) for j in range(-1, height + 1) if not (0 <= i < width and 0 <= j < height)]
            if not any(is_street(city, *c) for c in ring):          # a house stands along a street
                continue
            candidates.append((distance, _tie(city_id, x0, y0), x0, y0))
    candidates.sort()
    taken, lots = set(), []
    for _, _, x0, y0 in candidates:
        cells = {(x0 + i, y0 + j) for i in range(width) for j in range(height)}
        if cells & taken:
            continue
        taken |= cells
        lots.append((x0, y0))
    return tuple(lots)


def plan(city_id):
    """Ordered lots (x, y of the top-left cell) of a city's houses, nearest to the centre first."""
    return list(_plan(city_id))


def house_id(city_id, x, y):
    return hashlib.sha1(("town:%s:%d:%d" % (city_id, x, y)).encode()).hexdigest()[:32]


# ---------- targets ----------
def economic_population(db, ph):
    row = db.execute("SELECT next_population FROM population ORDER BY month_index DESC LIMIT 1").fetchone()
    return int(row[0]) if row else 200


def target_houses(city, population=None):
    if city["id"] == GAME_CITY:
        return max(GAME_CITY_MIN_HOUSES, int(population if population is not None else 200) // HOUSE_CAPACITY)
    return max(OTHER_CITY_MIN, min(OTHER_CITY_MAX, city["radius"] // 2))


# ---------- writing ----------
def _count(db, ph, city_id):
    return int(db.execute(_q("SELECT COUNT(*) FROM buildings WHERE owner=%s AND kind=%s", ph), (owner_of(city_id), HOUSE_KIND)).fetchone()[0])


def _blocked(db, ph, city):
    r = city["radius"] + 2
    box = (city["x"] - r, city["x"] + r, city["y"] - r, city["y"] + r)
    blocked = {(x, y) for x, y in db.execute(_q("SELECT x,y FROM cells WHERE x BETWEEN %s AND %s AND y BETWEEN %s AND %s", ph), box).fetchall()}
    blocked |= {(x, y) for x, y in db.execute(_q("SELECT x,y FROM roads WHERE x BETWEEN %s AND %s AND y BETWEEN %s AND %s", ph), box).fetchall()}
    return blocked


def _create_house(db, ph, city_id, x, y, now):
    object_id = house_id(city_id, x, y)
    owner = owner_of(city_id)
    footprint = [(x + i, y + j) for i in range(HOUSE_SIZE[0]) for j in range(HOUSE_SIZE[1])]
    db.execute(_q("INSERT INTO buildings(id,owner,kind,x,y,created) VALUES(%s,%s,%s,%s,%s,%s)", ph), (object_id, owner, HOUSE_KIND, x, y, now))
    for a, b in footprint:          # a loop, not executemany: a psycopg connection has no executemany
        db.execute(_q("INSERT INTO cells(x,y,object_id) VALUES(%s,%s,%s)", ph), (a, b, object_id))
    grouped = {}
    for a, b in footprint:
        grouped.setdefault((a // CHUNK, b // CHUNK), []).append([a, b])
    for (cx, cy), coords in sorted(grouped.items()):
        db.execute(_q("INSERT INTO chunks(cx,cy,version) VALUES(%s,%s,1) ON CONFLICT(cx,cy) DO UPDATE SET version=chunks.version+1", ph), (cx, cy))
        version = db.execute(_q("SELECT version FROM chunks WHERE cx=%s AND cy=%s", ph), (cx, cy)).fetchone()[0]
        payload = json.dumps({"object_id": object_id, "owner": owner, "cells": coords, "building_kind": HOUSE_KIND})
        db.execute(_q("INSERT INTO events(cx,cy,version,kind,payload) VALUES(%s,%s,%s,%s,%s)", ph), (cx, cy, version, "building_created", payload))
    return object_id


def _remember(db, ph, city_id, now):
    db.execute(_q("DELETE FROM geo_seed WHERE city_id=%s", ph), (city_id,))
    db.execute(_q("INSERT INTO geo_seed(city_id,houses,version,updated) VALUES(%s,%s,%s,%s)", ph), (city_id, _count(db, ph, city_id), VERSION, now))


def seed_city(db, ph, city_id, now, population=None, max_new=None, dry_run=False):
    """Bring a city up to its target number of houses. Idempotent: existing houses count, occupied lots are skipped."""
    city = geo.get_city(city_id)
    if city is None:
        raise ValueError("unknown city")
    target = target_houses(city, population)
    have = _count(db, ph, city_id)
    lots = plan(city_id)
    result = {"city_id": city_id, "name": city["name"], "target": target, "existing": have, "plan_size": len(lots), "placed": 0}
    need = max(0, target - have)
    if max_new is not None:
        need = min(need, max_new)
    if need == 0:
        return result
    blocked = _blocked(db, ph, city)
    own_ids = {r[0] for r in db.execute(_q("SELECT id FROM buildings WHERE owner=%s", ph), (owner_of(city_id),)).fetchall()}
    for x, y in lots:
        if result["placed"] >= need:
            break
        if house_id(city_id, x, y) in own_ids:
            continue
        cells = {(x + i, y + j) for i in range(HOUSE_SIZE[0]) for j in range(HOUSE_SIZE[1])}
        if cells & blocked:
            continue
        if not dry_run:
            _create_house(db, ph, city_id, x, y, now)
            blocked |= cells
        result["placed"] += 1
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
