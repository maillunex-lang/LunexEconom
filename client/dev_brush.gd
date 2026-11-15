extends RefCounted
## Server caps each command at 25 unique cells.
static func cells(center: Vector2i, size: int) -> Array:
    var result: Array = []
    if size not in [1, 3, 5]:
        return result
    var radius := size / 2
    for y in range(-radius, radius + 1):
        for x in range(-radius, radius + 1):
            result.append([center.x + x, center.y + y])
    return result