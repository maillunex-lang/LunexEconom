extends RefCounted
## Deterministic road graph prototype. Roads are orthogonal tile edges.
## Production MMO must persist roads and validate commands on the server.
const SEED := 18273
const ARM := 4                  # the crossroads in a city centre: two roads of 2*ARM+1 cells (mirrors server/roads.py)
const RIVER_X := 230
const RIVER_KNOT := 64
## Centres of the 20 cities (server/geo.py); parity is checked by server/test_roads.py.
const CITY_CENTERS: Array[Vector2i] = [Vector2i(0, 0), Vector2i(-3, 373), Vector2i(-12, 453), Vector2i(-328, -450), Vector2i(-481, 87), Vector2i(468, 260), Vector2i(520, 676), Vector2i(-7, 593), Vector2i(-36, 659), Vector2i(-435, 46), Vector2i(14, 430), Vector2i(-82, -226), Vector2i(-356, 209), Vector2i(-212, -250), Vector2i(453, 717), Vector2i(668, 128), Vector2i(-180, 174), Vector2i(2, -97), Vector2i(-391, -388), Vector2i(-199, -511)]
var segments: Dictionary = {}

static func is_base_road(cell: Vector2i) -> bool:
    for center in CITY_CENTERS:
        if (cell.x == center.x and absi(cell.y - center.y) <= ARM) or (cell.y == center.y and absi(cell.x - center.x) <= ARM):
            return true
    return false

static func terrain_noise(x: int, y: int) -> int:
    var h := (x * 73856093) ^ (y * 19349663) ^ SEED
    h = (h ^ (h >> 13)) * 1274126177
    return posmod(h ^ (h >> 16), 100)

## Centre column of the river in row y (integer maths, identical to server/roads.py::river_x).
static func river_x(y: int) -> int:
    var k: int = floori(float(y) / float(RIVER_KNOT))
    var r: int = y - k * RIVER_KNOT
    var a: int = terrain_noise(k, 7919) * 2 / 5
    var b: int = terrain_noise(k + 1, 7919) * 2 / 5
    return RIVER_X - 20 + (a * (RIVER_KNOT - r) + b * r) / RIVER_KNOT

static func is_water(cell: Vector2i) -> bool:
    return absi(cell.x - river_x(cell.y)) <= 1 and not is_base_road(cell)

func is_road(cell: Vector2i) -> bool:
    return segments.has(cell) or is_base_road(cell)

func neighbors(cell: Vector2i) -> Array[Vector2i]:
    var result: Array[Vector2i] = []
    for step in [Vector2i(1, 0), Vector2i(-1, 0), Vector2i(0, 1), Vector2i(0, -1)]:
        var next: Vector2i = cell + step
        if is_road(next):
            result.append(next)
    return result

func connect_site(site: Vector2i, max_distance: int = 128) -> Array[Vector2i]:
    # Candidate path, not committed until server-side validation exists.
    # Connect to the nearest cell of a city crossroads with a Manhattan path.
    var target := site
    var best := 1 << 30
    for center in CITY_CENTERS:
        for candidate in [Vector2i(center.x, clampi(site.y, center.y - ARM, center.y + ARM)), Vector2i(clampi(site.x, center.x - ARM, center.x + ARM), center.y)]:
            var distance: int = absi(candidate.x - site.x) + absi(candidate.y - site.y)
            if distance < best:
                best = distance
                target = candidate
    var path: Array[Vector2i] = [site]
    var current := site
    while current != target and path.size() <= max_distance:
        if current.x != target.x:
            current.x += 1 if current.x < target.x else -1
        else:
            current.y += 1 if current.y < target.y else -1
        path.append(current)
    if current != target:
        return []
    return path

func add_path(path: Array[Vector2i]) -> bool:
    if path.is_empty():
        return false
    for i in range(1, path.size()):
        var delta: Vector2i = path[i] - path[i - 1]
        if absi(delta.x) + absi(delta.y) != 1:
            return false
    if not is_road(path[path.size() - 1]):
        return false
    for cell in path:
        segments[cell] = true
    return true

func route(start: Vector2i, destination: Vector2i, max_visited: int = 12000) -> Array[Vector2i]:
    if not is_road(start) or not is_road(destination):
        return []
    var queue: Array[Vector2i] = [start]
    var head := 0
    var previous: Dictionary = {start: start}
    while head < queue.size() and head < max_visited:
        var current: Vector2i = queue[head]
        head += 1
        if current == destination:
            var path: Array[Vector2i] = []
            var cursor := destination
            while cursor != start:
                path.push_front(cursor)
                cursor = previous[cursor]
            path.push_front(start)
            return path
        for next in neighbors(current):
            if not previous.has(next):
                previous[next] = current
                queue.append(next)
    return []
