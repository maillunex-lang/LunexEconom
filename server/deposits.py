"""Finite mineral deposits (BE-108).

Placement is a pure function of the world seed and ``geo`` city centres: the same
database always grows the same patches. A cell is rejected when ``roads.is_water``
or ``roads.is_base_road`` is true, so deposits sit off the city crossroads and off
the river. Legacy ``mine`` buildings are not deposits: they keep producing oil
anywhere (see docs/INDUSTRIES.md). New extractors refuse ``/build`` with
``no_deposit`` unless the footprint covers a matching patch that still has stock
and is not already taken.
"""
import hashlib

import geo
import goods_catalog
import regions
import roads

SEED = geo.SEED
RESOURCES = ("oil", "gas", "sand", "forest", "iron", "coal", "stone", "flax")
# How many patches of each resource to drop around every city. New resources are appended
# so the earlier oil/gas/sand/forest coordinates stay put.
COUNTS = {"oil": 2, "gas": 1, "sand": 1, "forest": 1, "iron": 1, "coal": 1, "stone": 1, "flax": 1}
PATCH = (2, 2)          # deposit rectangle; the 3x3 pad around it stays dry and off the crossroads
PAD = 3
INITIAL = {"oil": 2400, "gas": 6400, "sand": 12000, "forest": 5600,
           "iron": 3200, "coal": 11200, "stone": 16000, "flax": 8000}

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS deposits(id TEXT PRIMARY KEY, resource TEXT NOT NULL, region TEXT NOT NULL, "
    "x INTEGER NOT NULL, y INTEGER NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL, "
    "initial_qty BIGINT NOT NULL, remaining BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS building_deposits(object_id TEXT PRIMARY KEY, deposit_id TEXT NOT NULL, resource TEXT NOT NULL)",
)


def _q(sql, ph):
    return sql.replace("%s", ph)


def ensure(db, ph):
    for statement in SCHEMA:
        db.execute(statement)
    expected = len(geo.cities()) * sum(COUNTS.values())
    have_n = int(db.execute("SELECT COUNT(*) FROM deposits").fetchone()[0] or 0)
    if have_n >= expected:
        return 0
    have = {row[0] for row in db.execute("SELECT id FROM deposits").fetchall()}
    created = 0
    for item in layout():
        if item["id"] in have:
            continue
        db.execute(_q("INSERT INTO deposits(id,resource,region,x,y,width,height,initial_qty,remaining) "
                      "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)", ph),
                   (item["id"], item["resource"], item["region"], item["x"], item["y"], item["width"], item["height"],
                    item["initial"], item["initial"]))
        created += 1
    return created


def _mix(region, resource, index, salt):
    digest = hashlib.sha256(("%s:%s:%s:%s:%s" % (SEED, region, resource, index, salt)).encode()).digest()
    return int.from_bytes(digest[:4], "big")


def _pad_clear(x, y):
    for dx in range(PAD):
        for dy in range(PAD):
            if roads.is_water(x + dx, y + dy) or roads.is_base_road(x + dx, y + dy):
                return False
    return True


def _hits(x, y, taken):
    for ox, oy in taken:
        if abs(x - ox) < PAD and abs(y - oy) < PAD:
            return True
    return False


_LAYOUT = None


def layout():
    """Deterministic deposit list. Does not touch the database. Cached: the seed does not change."""
    global _LAYOUT
    if _LAYOUT is None:
        _LAYOUT = _layout()
    return _LAYOUT


def _layout():
    placed = []
    taken = []
    for city in geo.cities():
        cx, cy = int(city["x"]), int(city["y"])
        for resource in RESOURCES:
            for index in range(COUNTS[resource]):
                found = None
                for attempt in range(160):
                    hop = _mix(city["id"], resource, index, attempt)
                    dx = 5 + (attempt % 12)
                    dy = 5 + (hop % 9)
                    sx = 1 if (hop // 9) % 2 == 0 else -1
                    sy = 1 if (hop // 18) % 2 == 0 else -1
                    x, y = cx + sx * dx, cy + sy * dy
                    if not _pad_clear(x, y) or _hits(x, y, taken):
                        continue
                    if regions.region_of(x, y) != city["id"]:
                        continue
                    found = (x, y)
                    break
                if found is None:
                    continue
                x, y = found
                width, height = PATCH
                taken.append((x, y))
                placed.append({
                    "id": "dep:%s:%s:%d" % (city["id"], resource, index),
                    "resource": resource, "region": city["id"],
                    "x": x, "y": y, "width": width, "height": height,
                    "initial": INITIAL[resource],
                })
    return placed


def _overlap(deposit, cells):
    x, y, w, h = deposit[0], deposit[1], deposit[2], deposit[3]
    for cx, cy in cells:
        if x <= cx < x + w and y <= cy < y + h:
            return True
    return False


def gate(db, ph, kind, cells):
    """Return ``{"deposit_id": ...}`` or ``{"error": "no_deposit"|"deposit_busy", ...}``.

    Kinds without a deposit (including the legacy ``mine``) return None.
    """
    resource = goods_catalog.deposit_resource(kind)
    if not resource:
        return None
    rows = db.execute(_q("SELECT id,x,y,width,height,remaining FROM deposits WHERE resource=%s ORDER BY id", ph), (resource,)).fetchall()
    match = None
    for dep_id, x, y, w, h, remaining in rows:
        if _overlap((int(x), int(y), int(w), int(h)), cells):
            match = (dep_id, int(remaining))
            break
    if match is None or match[1] <= 0:
        return {"error": "no_deposit", "resource": resource}
    busy = db.execute(_q("SELECT object_id FROM building_deposits WHERE deposit_id=%s", ph), (match[0],)).fetchone()
    if busy:
        alive = db.execute(_q("SELECT 1 FROM buildings WHERE id=%s", ph), (busy[0],)).fetchone()
        if alive:
            return {"error": "deposit_busy", "resource": resource, "deposit_id": match[0]}
        db.execute(_q("DELETE FROM building_deposits WHERE deposit_id=%s", ph), (match[0],))
    return {"deposit_id": match[0], "resource": resource}


def link(db, ph, object_id, deposit_id, resource):
    db.execute(_q("INSERT INTO building_deposits(object_id,deposit_id,resource) VALUES(%s,%s,%s)", ph),
               (object_id, deposit_id, resource))


def release(db, ph, object_id):
    db.execute(_q("DELETE FROM building_deposits WHERE object_id=%s", ph), (object_id,))


def load_remaining(db, ph):
    """``{object_id: [deposit_id, remaining]}`` for wells that are still linked."""
    rows = db.execute("SELECT b.object_id,b.deposit_id,d.remaining FROM building_deposits b "
                      "JOIN deposits d ON d.id=b.deposit_id").fetchall()
    return {object_id: [deposit_id, int(remaining)] for object_id, deposit_id, remaining in rows}


def draw(state, object_id, qty):
    """Take up to ``qty`` from a linked deposit. Unknown wells produce nothing."""
    slot = state.get(object_id)
    if slot is None or qty <= 0:
        return 0
    take = min(int(qty), slot[1])
    slot[1] -= take
    return take


def store_remaining(db, ph, state):
    for object_id, (deposit_id, left) in state.items():
        db.execute(_q("UPDATE deposits SET remaining=%s WHERE id=%s", ph), (int(left), deposit_id))


def query(db, ph, x0, y0, x1, y1):
    rows = db.execute(_q(
        "SELECT id,resource,region,x,y,width,height,initial_qty,remaining FROM deposits "
        "WHERE x<=%s AND x+width-1>=%s AND y<=%s AND y+height-1>=%s ORDER BY id", ph),
        (x1, x0, y1, y0)).fetchall()
    return {"version": goods_catalog.CATALOG_VERSION, "seed": SEED, "bbox": [x0, y0, x1, y1],
            "deposits": [{"id": i, "resource": r, "region": g, "x": int(x), "y": int(y),
                          "width": int(w), "height": int(h), "initial": int(initial), "remaining": int(left)}
                         for i, r, g, x, y, w, h, initial, left in rows]}


def open_origins(db, ph, resource):
    """Anchor cells of deposits that still have stock and no live building. Stable order."""
    rows = db.execute(_q(
        "SELECT d.id,d.x,d.y FROM deposits d WHERE d.resource=%s AND d.remaining>0 AND d.id NOT IN ("
        "SELECT b.deposit_id FROM building_deposits b JOIN buildings g ON g.id=b.object_id) ORDER BY d.id", ph),
        (resource,)).fetchall()
    return [(int(x), int(y), dep_id) for dep_id, x, y in rows]


def parse_bbox(args):
    """``args`` is a ``parse_qs`` dict. Returns (x0,y0,x1,y1) or None."""
    try:
        x0, y0, x1, y1 = (int(args[key][0]) for key in ("x0", "y0", "x1", "y1"))
    except (KeyError, ValueError, IndexError, TypeError):
        return None
    if x0 > x1 or y0 > y1 or x1 - x0 > 2000 or y1 - y0 > 2000:
        return None
    return x0, y0, x1, y1
