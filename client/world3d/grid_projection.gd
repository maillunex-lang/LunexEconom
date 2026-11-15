extends RefCounted
## Visual mapping only. Server coordinates and ownership remain authoritative.
const CELL_METERS := 2.0
const CHUNK_CELLS := 12

static func cell_to_world(cell: Vector2i) -> Vector3:
    return Vector3(float(cell.x) * CELL_METERS, 0.0, float(cell.y) * CELL_METERS)

static func world_to_cell(position: Vector3) -> Vector2i:
    return Vector2i(roundi(position.x / CELL_METERS), roundi(position.z / CELL_METERS))

static func chunk_for(cell: Vector2i) -> Vector2i:
    return Vector2i(floori(float(cell.x) / CHUNK_CELLS), floori(float(cell.y) / CHUNK_CELLS))

static func cell_from_ground_ray(origin: Vector3, direction: Vector3) -> Vector2i:
    if absf(direction.y) < 0.0001:
        return Vector2i(-2147483648, -2147483648)
    var distance := -origin.y / direction.y
    if distance < 0.0:
        return Vector2i(-2147483648, -2147483648)
    return world_to_cell(origin + direction * distance)