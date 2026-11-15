"""Pure integer world generation shared by server and future Android client.

Coordinates are unbounded signed integers. No floating point operations.
"""
CELL_METERS = 20
CHUNK_CELLS = 12
MASK = (1 << 64) - 1


def mix64(value):
    """Unsigned SplitMix64 finalizer, with explicitly wrapped 64-bit arithmetic."""
    value = (value ^ (value >> 30)) * 0xbf58476d1ce4e5b9 & MASK
    value = (value ^ (value >> 27)) * 0x94d049bb133111eb & MASK
    return (value ^ (value >> 31)) & MASK


def noise(seed, x, y):
    if any(type(v) is not int for v in (seed, x, y)):
        raise TypeError("seed and coordinates must be integers")
    return mix64((seed & MASK) ^ mix64(x & MASK) ^ ((mix64(y & MASK) << 1) & MASK))


def terrain(seed, x, y):
    """One river meanders across the whole map; deterministic sparse trees."""
    river_center = (noise(seed ^ 0x7269766572, 0, y // 24) % 81) - 40
    # River center is interpolated with integer arithmetic between anchors.
    y0 = y // 24
    offset = y - y0 * 24
    next_center = (noise(seed ^ 0x7269766572, 0, y0 + 1) % 81) - 40
    river_center = (river_center * (24 - offset) + next_center * offset) // 24
    if abs(x - river_center) <= 2:
        return "water"
    return "tree" if noise(seed, x, y) % 13 == 0 else "ground"


def chunk(seed, cx, cy):
    if type(cx) is not int or type(cy) is not int:
        raise TypeError("chunk coordinates must be integers")
    return {
        "cx": cx,
        "cy": cy,
        "size": CHUNK_CELLS,
        "terrain": [
            [terrain(seed, cx * CHUNK_CELLS + dx, cy * CHUNK_CELLS + dy)
             for dx in range(CHUNK_CELLS)]
            for dy in range(CHUNK_CELLS)
        ],
    }


def radius_at_level(base_radius, level):
    if type(base_radius) is not int or base_radius < 1 or type(level) is not int or not 1 <= level <= 6:
        raise ValueError("invalid radius or level")
    radius = base_radius
    for _ in range(level - 1):
        radius = (radius * 125 + 99) // 100
    return radius


def zone(x, y, city_x, city_y, base_radius, level):
    """Square-ring zoning; old inner ring never changes with city growth."""
    dx, dy = x - city_x, y - city_y
    distance = max(abs(dx), abs(dy))
    if distance > radius_at_level(base_radius, level):
        return "free"
    if distance <= max(1, base_radius // 5):
        return "center"
    # Stable zoning per ring: once allocated, a cell keeps its zone.
    ring = next(n for n in range(1, level + 1) if distance <= radius_at_level(base_radius, n))
    outer = radius_at_level(base_radius, ring)
    # Eastern wedge of the outer band is industrial.
    if dx > 0 and abs(dy) * 2 <= dx and distance * 4 >= outer * 3:
        return "industrial"
    return "residential"


def build_allowed(building, zone_name):
    return zone_name in building["zones"]


def travel_game_hours(road_meters, speed_kmh=85):
    """Integer minutes, rounded up, from road meters at km/h."""
    if type(road_meters) is not int or road_meters < 0 or type(speed_kmh) is not int or speed_kmh <= 0:
        raise ValueError("invalid road distance or speed")
    return (road_meters * 60 + speed_kmh * 1000 - 1) // (speed_kmh * 1000)


def connected(roads, start, end):
    """Four-neighbour BFS for road-cell connectivity."""
    if start not in roads or end not in roads:
        return False
    seen = {start}
    queue = [start]
    for x, y in queue:
        if (x, y) == end:
            return True
        for node in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if node in roads and node not in seen:
                seen.add(node)
                queue.append(node)
    return False
