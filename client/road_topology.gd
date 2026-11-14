extends RefCounted
## 0.2.7: pure road topology helper. World coordinates, not chunk-local.
## Bit flags: north=1, east=2, south=4, west=8.
const NORTH := 1
const EAST := 2
const SOUTH := 4
const WEST := 8

static func mask_at(roads: Object, cell: Vector2i) -> int:
    if not roads.is_road(cell):
        return 0
    var mask := 0
    if roads.is_road(cell + Vector2i(0, -1)): mask |= NORTH
    if roads.is_road(cell + Vector2i(1, 0)): mask |= EAST
    if roads.is_road(cell + Vector2i(0, 1)): mask |= SOUTH
    if roads.is_road(cell + Vector2i(-1, 0)): mask |= WEST
    return mask

static func shape(mask: int) -> String:
    var count := 0
    for bit in [NORTH, EAST, SOUTH, WEST]:
        if mask & bit: count += 1
    match count:
        0: return "isolated"
        1: return "end"
        2:
            if mask == NORTH | SOUTH or mask == EAST | WEST:
                return "straight"
            return "corner"
        3: return "t_junction"
        4: return "cross"
    return "invalid"

static func affected_cells(cell: Vector2i) -> Array[Vector2i]:
    # A road edit changes the visual topology of four adjacent cells too.
    return [cell, cell + Vector2i(0, -1), cell + Vector2i(1, 0), cell + Vector2i(0, 1), cell + Vector2i(-1, 0)]
