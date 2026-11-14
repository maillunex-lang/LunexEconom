extends RefCounted
## Deterministic city *background*. Does not own game cells or modify roads.
const SEED := 18273
# Only twenty IDs. Avoid hashing the same UTF-8 string for every visible tile.
static var city_seed_cache: Dictionary = {}

static func _city_seed(city_id: String) -> int:
    if city_seed_cache.has(city_id):
        return int(city_seed_cache[city_id])
    var value: int = 2166136261
    for byte in city_id.to_utf8_buffer():
        value = ((value ^ int(byte)) * 16777619) & 0x7fffffff
    city_seed_cache[city_id] = value
    return value

static func _tile_noise(city_id: String, x: int, y: int) -> int:
    var h: int = (x * 73856093) ^ (y * 19349663) ^ _city_seed(city_id) ^ SEED
    h = (h ^ (h >> 13)) * 1274126177
    return posmod(h ^ (h >> 16), 1000)

static func visual_at(city: Dictionary, x: int, y: int, terrain_kind: int) -> String:
    # Water, vegetation, authoritative buildings and roads always win.
    if terrain_kind not in [0, 1, 2]:
        return ""
    var cx: int = int(city.get("x", 0))
    var cy: int = int(city.get("y", 0))
    var radius: int = int(city.get("radius", 0))
    if radius < 1:
        return ""
    var delta := Vector2(float(x - cx), float(y - cy))
    var distance := delta.length()
    if distance > float(radius):
        return ""
    var id: String = str(city.get("id", ""))
    var density := distance / float(radius)
    var offset_x := _city_seed(id) % 11
    var offset_y := (_city_seed(id) / 13) % 11
    var spacing := 7 if density < 0.52 else 11
    # An intentional readable street grid, not a copy of any real city layout.
    if posmod(x + offset_x, spacing) == 0 or posmod(y + offset_y, spacing) == 0:
        return "street"
    if abs(x - cx) < 3 and abs(y - cy) < 3:
        return "square"
    var n := _tile_noise(id, x, y)
    var industrial := str(city.get("specialization", "")).contains("нефть") or str(city.get("specialization", "")).contains("металлургия") or str(city.get("specialization", "")).contains("добыча") or str(city.get("specialization", "")).contains("промышленность")
    if density > 0.72 and density < 0.94 and industrial and n < 150:
        return "industrial"
    var chance := 660 if density < 0.40 else (390 if density < 0.72 else 145)
    return "house" if n < chance else ""

static func cities_in_chunk(cities: Array, chunk: Vector2i, chunk_size: int = 12) -> Array:
    var minx := chunk.x * chunk_size
    var miny := chunk.y * chunk_size
    var maxx := minx + chunk_size - 1
    var maxy := miny + chunk_size - 1
    var visible: Array = []
    for city in cities:
        if not city is Dictionary:
            continue
        var x: int = int(city.get("x", 0))
        var y: int = int(city.get("y", 0))
        var r: int = int(city.get("radius", 0))
        if x + r >= minx and x - r <= maxx and y + r >= miny and y - r <= maxy:
            visible.append(city)
    return visible
