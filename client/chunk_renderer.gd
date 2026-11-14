extends Node2D
## One cached canvas item per 12x12 chunk, redrawn only when terrain/roads change.
const TILE_W := 96.0
const TILE_H := 48.0
const CHUNK := 12
const TOPOLOGY = preload("res://road_topology.gd")
const CITY_LAYOUT = preload("res://city_layout.gd")
const SEASONS = preload("res://season_visual.gd")
const COLORS := [Color("#63865b"), Color("#72915e"), Color("#8ca66a"), Color("#b6a36d"), Color("#527f8d"), Color("#547c54"), Color("#b46f49")]
var world: Node2D
var chunk_coord: Vector2i
var draw_count: int = 0
var last_draw_usec: int = 0

## Read with Engine.get_frames_per_second() in debug HUD; no per-frame redraws.

func _draw() -> void:
    if world == null: return
    var start_usec: int = Time.get_ticks_usec()
    var footprint: Array[Vector2i] = []
    var season_month := -1
    var seasons_on := false
    var host = world.get_parent()
    if host != null:
        var clock_data = host.get("game_clock")
        if clock_data is Dictionary and not clock_data.is_empty():
            var span := maxi(int(clock_data.get("month_seconds", 86400)), 1)
            var elapsed := maxf(Time.get_unix_time_from_system() + float(host.get("clock_offset")) - float(clock_data.get("epoch", 0)), 0.0)
            season_month = int(clock_data.get("base_index", 0)) + int(elapsed / span)
            seasons_on = bool(host.get("seasons_enabled"))
    var preview_ok: bool = false
    if not world.build_type.is_empty():
        footprint = world.planner.footprint(world.selected, world.build_size(world.build_type))
        preview_ok = bool(world.preview_build(world.selected).get("ok", false))
    for x in range(chunk_coord.x * CHUNK, (chunk_coord.x + 1) * CHUNK):
        for y in range(chunk_coord.y * CHUNK, (chunk_coord.y + 1) * CHUNK):
            if absi(x) > world.expansion_radius or absi(y) > world.expansion_radius: continue
            var p: Vector2 = world.iso(float(x), float(y))
            var pts := PackedVector2Array([p + Vector2(0, -TILE_H / 2), p + Vector2(TILE_W / 2, 0), p + Vector2(0, TILE_H / 2), p + Vector2(-TILE_W / 2, 0)])
            var kind: int = world.cell_kind(x, y)
            var color: Color = COLORS[kind]
            if seasons_on and kind not in [3, 6]:
                color = SEASONS.tinted(color, season_month, true)
            draw_colored_polygon(pts, color)
            # The empty world has no background roads, streets or houses: roads are only the city crossroads and the access roads of buildings.

            if kind == 3:
                _draw_road(p, Vector2i(x, y))
            if kind == 6:
                var cell := Vector2i(x, y)
                var owner := ""
                if world.server_cells.has(cell):
                    owner = str(world.server_cells[cell].get("owner", ""))
                if _is_primary_building_cell(cell):
                    _draw_building(p, world.building_at(cell), owner, cell)
            if not footprint.is_empty() and Vector2i(x, y) in footprint:
                var tint := Color(0.22, 0.95, 0.50, 0.45) if preview_ok else Color(0.98, 0.22, 0.22, 0.45)
                draw_colored_polygon(pts, tint)
            # No per-tile outline; roads and selected cells remain distinguishable.
            if kind == 5:
                draw_circle(p + Vector2(0, -10), 9, Color("#305e43"))
                draw_circle(p + Vector2(3, -15), 6, Color("#477b4d"))
            if world.selected == Vector2i(x, y):
                draw_polyline(PackedVector2Array([pts[0], pts[1], pts[2], pts[3], pts[0]]), Color("#f8d46a"), 3.0)
    draw_count += 1
    last_draw_usec = Time.get_ticks_usec() - start_usec

func _draw_road(p: Vector2, cell: Vector2i) -> void:
    # Asphalt occupies the entire 2:1 diamond, so adjacent road cells join
    # edge-to-edge without floating strips or yellow lines at intersections.
    # Topology is still used by construction/pathfinding, not painted as rails.
    var mask: int = TOPOLOGY.mask_at(world.roads, cell)
    var diamond := PackedVector2Array([
        p + Vector2(0, -TILE_H * 0.5),
        p + Vector2(TILE_W * 0.5, 0),
        p + Vector2(0, TILE_H * 0.5),
        p + Vector2(-TILE_W * 0.5, 0)
    ])
    if world.remote_art != null:
        var road_tex: Texture2D = world.remote_art.texture_for("roads.straight")
        if road_tex != null:
            draw_texture_rect(road_tex, Rect2(p - Vector2(TILE_W * 0.5, TILE_H * 0.5), Vector2(TILE_W, TILE_H)), false)
            return
    draw_colored_polygon(diamond, Color("#454b50"))
    # Restrained, non-repeating grain; no lane markings on road tiles.
    if mask >= 0:
        var grain := float(posmod(cell.x * 37 + cell.y * 53, 9)) / 255.0
        draw_circle(p + Vector2(-8, 1), 1.2, Color(0.36 + grain, 0.38 + grain, 0.40 + grain, 0.20))

## Draw one sprite per server object, not one per occupied tile.
## Missing object IDs retain legacy cell-by-cell behavior.
func _is_primary_building_cell(cell: Vector2i) -> bool:
    if not world.server_cells.has(cell):
        return true
    var object_id := str(world.server_cells[cell].get("object_id", ""))
    if object_id.is_empty():
        return true
    for dx in range(-4, 5):
        for dy in range(-4, 5):
            var other := cell + Vector2i(dx, dy)
            if other == cell or not world.server_cells.has(other):
                continue
            if str(world.server_cells[other].get("object_id", "")) != object_id:
                continue
            if other.x < cell.x or (other.x == cell.x and other.y < cell.y):
                return false
    return true

func _object_center(cell: Vector2i) -> Vector2:
    if not world.server_cells.has(cell):
        return world.iso(float(cell.x), float(cell.y))
    var object_id := str(world.server_cells[cell].get("object_id", ""))
    if object_id.is_empty():
        return world.iso(float(cell.x), float(cell.y))
    var sum := Vector2.ZERO
    var count := 0
    for dx in range(-4, 5):
        for dy in range(-4, 5):
            var other := cell + Vector2i(dx, dy)
            if world.server_cells.has(other) and str(world.server_cells[other].get("object_id", "")) == object_id:
                sum += world.iso(float(other.x), float(other.y))
                count += 1
    return sum / float(maxi(count, 1))

func _owner_color(owner: String) -> Color:
    if owner.is_empty(): return Color("#9ca3a8")
    # Stable across clients; never use randomized String.hash() for owner colors.
    var value: int = 2166136261
    for byte in owner.to_utf8_buffer():
        value = (value ^ int(byte)) * 16777619 & 0x7fffffff
    return Color.from_hsv(float(value % 360) / 360.0, 0.58, 0.91)

## A small isometric cottage of the generated city. Four of them (one per cell of the 2x2 lot) make a terrace; no owner badge: it is the town's.
func _draw_house(p: Vector2) -> void:
    var v: int = posmod(int(round(p.x)) * 31 + int(round(p.y)) * 17, 4)
    var walls := [Color("#e8dcc0"), Color("#d9cdb0"), Color("#cfd8d4"), Color("#e2cdbd")]
    var roofs := [Color("#b5533f"), Color("#7e6a55"), Color("#4f6f63"), Color("#9b4a3a")]
    var wall: Color = walls[v]
    var roof: Color = roofs[v]
    var a := Vector2(-11, 0)
    var b := Vector2(0, 5.5)
    var c := Vector2(11, 0)
    var rise := Vector2(0, -8)
    draw_colored_polygon(PackedVector2Array([p + a, p + b, p + b + rise, p + a + rise]), wall.darkened(0.16))
    draw_colored_polygon(PackedVector2Array([p + b, p + c, p + c + rise, p + b + rise]), wall)
    draw_colored_polygon(PackedVector2Array([p + a + rise, p + b + rise, p + c + rise, p + Vector2(0, -15)]), roof)
    draw_colored_polygon(PackedVector2Array([p + a + rise, p + Vector2(0, -15), p + c + rise]), roof.lightened(0.12))
    draw_rect(Rect2(p + Vector2(3, -6), Vector2(3, 5)), Color("#5b4636"))
    draw_rect(Rect2(p + Vector2(-7, -6), Vector2(3, 3)), Color("#a8c5d6"))

func _draw_building(p: Vector2, kind: String, owner: String = "", cell: Vector2i = Vector2i.ZERO) -> void:
    p = _object_center(cell)
    var art_id := ""
    match kind:
        "house":
            var variant := posmod(cell.x * 17 + cell.y * 31, 4)
            art_id = ["housing.small", "housing.panel_a", "housing.panel_b", "housing.apartment"][variant]
        "shop": art_id = "retail.grocery"
        "farm": art_id = "industry.farm"
        "mine": art_id = "industry.mine"
        "factory": art_id = "industry.factory"
        "warehouse": art_id = "industry.warehouse"
        "school": art_id = "municipal.school"
        "hospital": art_id = "municipal.hospital"
        "park": art_id = "municipal.park"
    if world.remote_art != null and not art_id.is_empty():
        var remote_tex: Texture2D = world.remote_art.texture_for(art_id)
        if remote_tex != null:
            var art_size: Vector2 = remote_tex.get_size()
            var factor: float = minf(1.0, 88.0 / maxf(art_size.x, 1.0))
            var display_size: Vector2 = art_size * factor
            draw_texture_rect(remote_tex, Rect2(p - Vector2(display_size.x * 0.5, display_size.y), display_size), false)
            return
    if kind == "house":
        _draw_house(p)
        return
    if world != null and world.patch_visuals != null:
        var tex: Texture2D = world.patch_visuals.texture_for(kind)
        if tex != null:
            # Keep ground anchoring consistent across replacement images.
            var size := tex.get_size()
            var scale_factor: float = minf(1.0, 88.0 / maxf(size.x, 1.0))
            var displayed := size * scale_factor
            draw_texture_rect(tex, Rect2(p - Vector2(displayed.x * 0.5, displayed.y), displayed), false)
            draw_circle(p + Vector2(0, -22), 5.5, _owner_color(owner))
            return
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
        "warehouse":
            wall = Color("#8a7d5c")
            roof = Color("#b5a47a")
        "shop":
            wall = Color("#d8efe4")
            roof = Color("#e7b45d")
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
    # Roof badge identifies the server-side owner; a local/procedural building stays neutral.
    draw_circle(p + Vector2(0, -22), 5.5, _owner_color(owner))
    draw_arc(p + Vector2(0, -22), 5.5, 0.0, TAU, 12, Color("#24343a"), 1.5)
    match kind:
        "farm":
            draw_line(p + Vector2(-13, -11), p + Vector2(-13, -21), Color("#f2dfb2"), 2.5)
            draw_line(p + Vector2(-17, -17), p + Vector2(-9, -17), Color("#f2dfb2"), 2.0)
        "mine":
            draw_line(p + Vector2(-13, -12), p + Vector2(-6, -24), Color("#303d48"), 2.5)
            draw_line(p + Vector2(-6, -24), p + Vector2(1, -12), Color("#303d48"), 2.5)
        "factory":
            draw_rect(Rect2(p + Vector2(8, -29), Vector2(6, 15)), Color("#536572"))
            draw_rect(Rect2(p + Vector2(9, -32), Vector2(4, 3)), Color("#e2e6e8"))
        "warehouse":
            draw_rect(Rect2(p + Vector2(-7, -9), Vector2(14, 9)), Color("#4b5c65"))
            draw_line(p + Vector2(-7, -5), p + Vector2(7, -5), Color("#e4c99d"), 1.5)
        "shop":
            draw_rect(Rect2(p + Vector2(-14, -8), Vector2(28, 6)), Color("#e7b45d"))
            draw_rect(Rect2(p + Vector2(-6, -2), Vector2(5, 7)), Color("#315647"))
            draw_rect(Rect2(p + Vector2(2, -2), Vector2(5, 7)), Color("#243b2f"))