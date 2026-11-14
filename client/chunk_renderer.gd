extends Node2D
## One cached canvas item per 12x12 chunk, redrawn only when terrain/roads change.
const TILE_W := 96.0
const TILE_H := 48.0
const CHUNK := 12
const TOPOLOGY = preload("res://road_topology.gd")
const COLORS := [Color("#63865b"), Color("#72915e"), Color("#8ca66a"), Color("#b6a36d"), Color("#527f8d"), Color("#547c54"), Color("#b46f49")]
var world: Node2D
var chunk_coord: Vector2i

func _draw() -> void:
    if world == null: return
    for x in range(chunk_coord.x * CHUNK, (chunk_coord.x + 1) * CHUNK):
        for y in range(chunk_coord.y * CHUNK, (chunk_coord.y + 1) * CHUNK):
            if absi(x) > world.expansion_radius or absi(y) > world.expansion_radius: continue
            var p: Vector2 = world.iso(float(x), float(y))
            var pts := PackedVector2Array([p + Vector2(0, -TILE_H / 2), p + Vector2(TILE_W / 2, 0), p + Vector2(0, TILE_H / 2), p + Vector2(-TILE_W / 2, 0)])
            var kind: int = world.cell_kind(x, y)
            draw_colored_polygon(pts, COLORS[kind])
            if kind == 3:
                _draw_road(p, Vector2i(x, y))
            if kind == 6:
                _draw_building(p, world.building_at(Vector2i(x, y)))
            if not world.build_type.is_empty():
                var footprint: Array[Vector2i] = world.planner.footprint(world.selected, world.build_size(world.build_type))
                if Vector2i(x, y) in footprint:
                    var check: Dictionary = world.preview_build(world.selected)
                    var tint := Color(0.22, 0.95, 0.50, 0.45) if check.get("ok", false) else Color(0.98, 0.22, 0.22, 0.45)
                    draw_colored_polygon(pts, tint)
            # No per-tile outline; roads and selected cells remain distinguishable.
            if kind == 5:
                draw_circle(p + Vector2(0, -10), 9, Color("#305e43"))
                draw_circle(p + Vector2(3, -15), 6, Color("#477b4d"))
            if world.selected == Vector2i(x, y):
                draw_polyline(PackedVector2Array([pts[0], pts[1], pts[2], pts[3], pts[0]]), Color("#f8d46a"), 3.0)
func _draw_road(p: Vector2, cell: Vector2i) -> void:
    var mask: int = TOPOLOGY.mask_at(world.roads, cell)
    var center := Color("#59636a")
    var asphalt := Color("#495159")
    var line := Color("#e2c985")
    draw_circle(p, 7.0, center)
    var directions := [
        [TOPOLOGY.NORTH, Vector2(0, -TILE_H * 0.5)],
        [TOPOLOGY.EAST, Vector2(TILE_W * 0.5, 0)],
        [TOPOLOGY.SOUTH, Vector2(0, TILE_H * 0.5)],
        [TOPOLOGY.WEST, Vector2(-TILE_W * 0.5, 0)]
    ]
    for item in directions:
        if mask & int(item[0]):
            draw_line(p, p + item[1], asphalt, 13.0, true)
            draw_line(p, p + item[1] * 0.9, line, 1.5, true)
    draw_circle(p, 4.5, center)

func _draw_building(p: Vector2, kind: String) -> void:
    var wall := Color("#b1a67c")
    var roof := Color("#d5c5a2")
    match kind:
        "farm":
            wall = Color("#b99462")
            roof = Color("#c94e3f")
        "mine":
            wall = Color("#676e75")
            roof = Color("#8d9ca4")
        "factory":
            wall = Color("#668b9d")
            roof = Color("#9eb7c1")
    var base := PackedVector2Array([
        p + Vector2(-22, -5), p + Vector2(0, 6),
        p + Vector2(22, -5), p + Vector2(0, -16)
    ])
    draw_colored_polygon(base, wall)
    draw_colored_polygon(PackedVector2Array([
        p + Vector2(-22, -5), p + Vector2(0, -24),
        p + Vector2(22, -5), p + Vector2(0, 6)
    ]), roof)
    draw_line(p + Vector2(-22, -5), p + Vector2(0, 6), Color("#3b4650"), 1.5)
