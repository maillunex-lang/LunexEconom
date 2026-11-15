extends RefCounted
## Pure server-to-visual adapter. A building is keyed by authoritative object_id.
const CHUNK := 12
var cells: Dictionary = {}
var objects: Dictionary = {}
var roads: Dictionary = {}

func apply_chunk(chunk: Vector2i, entries: Array) -> void:
    for x in range(chunk.x * CHUNK, (chunk.x + 1) * CHUNK):
        for y in range(chunk.y * CHUNK, (chunk.y + 1) * CHUNK):
            var cell := Vector2i(x, y)
            cells.erase(cell)
            roads.erase(cell)
    for entry in entries:
        if not entry is Dictionary:
            continue
        var x := int(entry.get("x", 0))
        var y := int(entry.get("y", 0))
        var coord := Vector2i(x, y)
        if coord.x < chunk.x * CHUNK or coord.x >= (chunk.x + 1) * CHUNK or coord.y < chunk.y * CHUNK or coord.y >= (chunk.y + 1) * CHUNK:
            continue
        if str(entry.get("kind", "")) == "road_changed":
            roads[coord] = true
        else:
            var oid := str(entry.get("object_id", ""))
            if not oid.is_empty():
                cells[coord] = {"object_id": oid, "kind": str(entry.get("building_kind", "")), "owner": str(entry.get("owner", ""))}
    _reindex()

func apply_event(event: Dictionary) -> void:
    var kind := str(event.get("kind", ""))
    if kind not in ["building_created", "building_removed", "road_changed"]:
        return
    var oid := str(event.get("object_id", ""))
    for xy in event.get("cells", []):
        if not xy is Array or xy.size() != 2:
            continue
        var cell := Vector2i(int(xy[0]), int(xy[1]))
        if kind == "road_changed":
            roads[cell] = true
        elif kind == "building_removed":
            if cells.has(cell) and str(cells[cell].get("object_id", "")) == oid:
                cells.erase(cell)
        elif not oid.is_empty():
            cells[cell] = {"object_id": oid, "kind": str(event.get("building_kind", "")), "owner": str(event.get("owner", ""))}
    _reindex()

func _reindex() -> void:
    objects.clear()
    for coord in cells:
        var data: Dictionary = cells[coord]
        var oid := str(data.get("object_id", ""))
        if not objects.has(oid):
            objects[oid] = {"id": oid, "kind": data["kind"], "owner": data["owner"], "footprint": []}
        objects[oid]["footprint"].append(coord)
    for oid in objects:
        objects[oid]["footprint"].sort_custom(func(a: Vector2i, b: Vector2i) -> bool: return a.x < b.x or (a.x == b.x and a.y < b.y))

func object_center(oid: String) -> Vector2:
    if not objects.has(oid):
        return Vector2.ZERO
    var cells_for_object: Array = objects[oid]["footprint"]
    var center := Vector2.ZERO
    for cell in cells_for_object:
        center += Vector2(cell)
    return center / float(cells_for_object.size())