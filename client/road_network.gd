extends RefCounted
## Deterministic road graph prototype. Roads are orthogonal tile edges.
## Production MMO must persist roads and validate commands on the server.
const SEED := 18273
var segments: Dictionary = {}

func is_road(cell: Vector2i) -> bool:
    return cell.x == 0 or cell.y == 0 or posmod(cell.x, 19) == 0 or posmod(cell.y, 23) == 0 or segments.has(cell)

func neighbors(cell: Vector2i) -> Array[Vector2i]:
    var result: Array[Vector2i] = []
    for step in [Vector2i(1, 0), Vector2i(-1, 0), Vector2i(0, 1), Vector2i(0, -1)]:
        var next: Vector2i = cell + step
        if is_road(next):
            result.append(next)
    return result

func connect_site(site: Vector2i, max_distance: int = 128) -> Array[Vector2i]:
    # Candidate path, not committed until server-side validation exists.
    # Connect to closest grid spine with a Manhattan path, preserving existing roads.
    var target := site
    var dx := min(posmod(site.x, 19), 19 - posmod(site.x, 19))
    var dy := min(posmod(site.y, 23), 23 - posmod(site.y, 23))
    if dx <= dy:
        target.x = int(round(float(site.x) / 19.0)) * 19
    else:
        target.y = int(round(float(site.y) / 23.0)) * 23
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
