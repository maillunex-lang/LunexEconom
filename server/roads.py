"""Server-authoritative road rules shared by SQLite and PostgreSQL backends.

Terrain and the base road grid mirror client/world.gd + client/road_network.gd
so client previews and server decisions agree. The server is the final authority.
"""
from collections import deque

SEED = 18273
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


def is_base_road(x, y):
    return x == 0 or y == 0 or x % 19 == 0 or y % 23 == 0


def is_water(x, y):
    return not is_base_road(x, y) and terrain_noise(x, y) < 8


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
