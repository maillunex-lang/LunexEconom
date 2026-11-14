extends Node2D
## One cached canvas item per 12x12 chunk, redrawn only when terrain/roads change.
const TILE_W := 96.0
const TILE_H := 48.0
const CHUNK := 12
const TOPOLOGY = preload("res://road_topology.gd")
const CITY_LAYOUT = preload("res://city_layout.gd")
const SEASONS = preload("res://season_visual.gd")
const TEST_SPRITES = preload("res://test_sprite_visuals.gd")
var test_sprites = TEST_SPRITES.new()

func _ready() -> void:
    AssetDownloader.finished.connect(_on_assets_ready)

func _on_assets_ready(_ok: bool) -> void:
    test_sprites.refresh()
    queue_redraw()
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
                _draw_test_building_or_fallback(p, cell, owner)
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
    var road_texture: Texture2D = test_sprites.texture_for("road")
    if road_texture != null:
        draw_texture_rect(road_texture, Rect2(p - Vector2(TILE_W * 0.5, TILE_H * 0.5), Vector2(TILE_W, TILE_H)), false)
        return
    draw_colored_polygon(diamond, Color("#454b50"))
    # Restrained, non-repeating grain; no lane markings on road tiles.
    if mask >= 0:
        var grain := float(posmod(cell.x * 37 + cell.y * 53, 9)) / 255.0
        draw_circle(p + Vector2(-8, 1), 1.2, Color(0.36 + grain, 0.38 + grain, 0.40 + grain, 0.20))

func _draw_test_building_or_fallback(p: Vector2, cell: Vector2i, owner: String) -> void:
    var kind: String = world.building_at(cell)
    if kind not in ["house", "shop"]:
        _draw_building(p, kind, owner)
        return
    var record: Dictionary = world.server_cells.get(cell, {})
    var object_id: String = str(record.get("object_id", ""))
    var anchor := cell
    var min_x := cell.x
    var max_x := cell.x
    var min_y := cell.y
    var max_y := cell.y
    if not object_id.is_empty():
        # Server stores one object_id across occupied cells. Draw once per object.
        for other in world.server_cells:
            if str(world.server_cells[other].get("object_id", "")) != object_id:
                continue
            min_x = mini(min_x, other.x)
            max_x = maxi(max_x, other.x)
            min_y = mini(min_y, other.y)
            max_y = maxi(max_y, other.y)
        anchor = Vector2i(min_x, min_y)
        if anchor != cell:
            return
    var cells_x := max_x - min_x + 1
    var cells_y := max_y - min_y + 1
    var is_long := kind == "house" and ((cells_x == 2 and cells_y == 1) or (cells_x == 1 and cells_y == 2))
    var key := "grocery" if kind == "shop" else test_sprites.house_variant(object_id, cell, is_long)
    var tex: Texture2D = test_sprites.texture_for(key)
    if tex == null:
        _draw_building(p, kind, owner)
        return
    var sprite_width: float = 170.0 if maxi(cells_x, cells_y) > 1 else 88.0
    var sprite_height: float = sprite_width * float(tex.get_height()) / maxf(float(tex.get_width()), 1.0)
    var center := world.iso(float(min_x + max_x) * 0.5, float(min_y + max_y) * 0.5)
    draw_texture_rect(tex, Rect2(center - Vector2(sprite_width * 0.5, sprite_height - 15.0), Vector2(sprite_width, sprite_height)), false)

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

func _draw_building(p: Vector2, kind: String, owner: String = "") -> void:
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
