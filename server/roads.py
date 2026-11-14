"""Server-authoritative road rules shared by SQLite and PostgreSQL backends.

Terrain and the base road grid mirror client/world.gd + client/road_network.gd
so client previews and server decisions agree. The server is the final authority.
"""
from collections import deque

SEED = 18273
ARM = 4                 # a city's crossroads: two roads of 2*ARM+1 cells through the city centre
RIVER_X = 230           # the river runs north-south between Ufa and Beloretsk; no city lies on it
RIVER_KNOT = 64         # rows between the points the river bends at
SEARCH_RADIUS = 32      # cells around the footprint loaded for access-road search
MAX_VISITED = 6000
DIRS = ((0, -1), (1, 0), (0, 1), (-1, 0))


def _wrap64(v):
    v &= (1 << 64) - 1
    return v - (1 << 64) if v >= (1 << 63) else v


def terrain_noise(x, y):
    """Same integer hash as GDScript cell_kind (64-bit wraparound, arithmetic shifts)."""
    h = _wrap64((x * 73856093) ^ (y * 19349663) ^ SEED)
    h = _wrap64((h ^ (h >> 13)) * 1274126177)
    return (h ^ (h >> 16)) % 100


def _centers():
    global _CENTERS
    if _CENTERS is None:
        import geo
        _CENTERS = tuple((c["x"], c["y"]) for c in geo.cities())
    return _CENTERS


_CENTERS = None


def is_base_road(x, y):
    """The only roads of the empty world: a crossroads in the centre of every city. All other roads are built by access paths."""
    for cx, cy in _centers():
        if (x == cx and abs(y - cy) <= ARM) or (y == cy and abs(x - cx) <= ARM):
            return True
    return False


def river_x(y):
    """Centre column of the river in row y: bends at every RIVER_KNOT rows, integer arithmetic only (mirrored in client/world.gd)."""
    k = y // RIVER_KNOT
    r = y - k * RIVER_KNOT
    a = terrain_noise(k, 7919) * 2 // 5
    b = terrain_noise(k + 1, 7919) * 2 // 5
    return RIVER_X - 20 + (a * (RIVER_KNOT - r) + b * r) // RIVER_KNOT


def is_water(x, y):
    """Water is one river and nothing else: no scattered ponds. A road cell is never water (bridge)."""
    return abs(x - river_x(y)) <= 1 and not is_base_road(x, y)


def search_box(footprint, radius=SEARCH_RADIUS):
    xs = [c[0] for c in footprint]
    ys = [c[1] for c in footprint]
    return min(xs) - radius, max(xs) + radius, min(ys) - radius, max(ys) + radius


def plan_access(footprint, dynamic_roads, occupied, max_coord):
    """Validate the footprint and plan the access road.

    Returns (error, path). `error` is None when the footprint is acceptable;
    `path` lists new road cells ordered from the building towards an existing
    road (empty when the footprint already touches a road).
    """
    fset = set(footprint)

    def road(c):
        return is_base_road(*c) or c in dynamic_roads

    for c in footprint:
        if road(c):
            return "road_overlap", []
        if is_water(*c):
            return "water", []
    if any(road((x + dx, y + dy)) for x, y in footprint for dx, dy in DIRS):
        return None, []

    def free(c):
        if c in fset or c in occupied or abs(c[0]) > max_coord or abs(c[1]) > max_coord:
            return False
        return road(c) or not is_water(*c)

    prev, queue = {}, deque()
    for x, y in footprint:
        for dx, dy in DIRS:
            s = (x + dx, y + dy)
            if s not in prev and free(s):
                prev[s] = s
                queue.append(s)
    visited = 0
    while queue and visited < MAX_VISITED:
        cur = queue.popleft()
        visited += 1
        if road(cur):
            path = []
            while prev[cur] != cur:
                path.append(cur)
                cur = prev[cur]
            path.append(cur)
            path.reverse()
            return None, path
        for dx, dy in DIRS:
            n = (cur[0] + dx, cur[1] + dy)
            if n not in prev and free(n):
                prev[n] = cur
                queue.append(n)
    return "no_road_access", []


def event_item(seq, cx, cy, version, kind, payload):
    """Rebuild a stored event. The event type always wins over payload fields;
    legacy rows stored the building type under "kind"."""
    import json
    data = json.loads(payload)
    if kind == "building_created" and "building_kind" not in data and "kind" in data:
        data["building_kind"] = data["kind"]
    data.pop("kind", None)
    return {"seq": seq, "cx": cx, "cy": cy, "version": version, "kind": kind, **data}
