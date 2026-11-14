extends Node2D
## Deterministic visual-only isometric world. No server authority or gameplay state.
const TILE_W := 96.0
const TILE_H := 48.0
const CHUNK := 12
const ROAD_SCRIPT = preload("res://road_network.gd")
const PLANNER_SCRIPT = preload("res://construction_planner.gd")
var planner = PLANNER_SCRIPT.new()
var build_type := ""
var building_records: Dictionary = {}
var build_counter := 0
const MAX_VISIBLE_CELLS := 4500
const CHUNK_SCRIPT = preload("res://chunk_renderer.gd")
var active_chunks: Dictionary = {}
var last_camera_position := Vector2.INF
var last_zoom := -1.0
var roads = ROAD_SCRIPT.new()
var server_cells: Dictionary = {}
var expansion_radius := 48
const SEED := 18273
const COLORS := [
    Color("#63865b"), Color("#72915e"), Color("#8ca66a"),
    Color("#b6a36d"), Color("#527f8d"), Color("#547c54")
]
var camera: Camera2D
var selected := Vector2i(-1, -1)
var touch_points: Dictionary = {}
var ui_touch_indices: Dictionary = {}
var ui_mouse_press := false
var dragging := false
var moved := false
var pinch_distance := 0.0
var last_mouse := Vector2.ZERO
# Frame-rate independent camera easing. Targets follow touch; visible camera catches up.
const PAN_RESPONSE := 13.0
const ZOOM_RESPONSE := 10.0
const PAN_SENSITIVITY := 0.78
const ZOOM_SENSITIVITY := 0.70
var target_position := Vector2.ZERO
var target_zoom := 1.0
var last_pinch_midpoint := Vector2.ZERO

func _ready() -> void:
    camera = Camera2D.new()
    camera.name = "WorldCamera"
    camera.enabled = true
    camera.position = Vector2(0, 300)
    camera.zoom = Vector2.ONE
    target_position = camera.position
    target_zoom = camera.zoom.x
    add_child(camera)
    _update_visible_chunks()

func cell_kind(x: int, y: int) -> int:
    var coord := Vector2i(x, y)
    if server_cells.has(coord):
        var kind := str(server_cells[coord].get("kind", ""))
        if kind == "road_changed": return 3
        if kind == "building_created" or kind in ["farm", "mine", "factory", "warehouse", "shop", "school", "hospital", "park"]: return 6
        if kind == "building_removed": return 0
    # Integer-only hash: independent of call order and frame rate.
    var h := (x * 73856093) ^ (y * 19349663) ^ SEED
    h = (h ^ (h >> 13)) * 1274126177
    var n := posmod(h ^ (h >> 16), 100)
    if planner.occupied.has(coord): return 6
    if roads.is_road(Vector2i(x, y)):
        return 3 # roads
    if n < 8:
        return 4 # water
    if n < 24:
        return 5 # trees
    return n % 3

func _is_building_event(kind: String) -> bool:
    return kind == "building_created" or kind in ["farm", "mine", "factory", "warehouse", "shop", "school", "hospital", "park"]

func _set_server_road(coord: Vector2i, present: bool) -> void:
    if present: roads.segments[coord] = true
    else: roads.segments.erase(coord)
    # A road edit changes the topology (junction shape) of the four neighbours too.
    for affected in preload("res://road_topology.gd").affected_cells(coord):
        _redraw_chunk_at(affected)

func apply_server_event(event: Dictionary) -> void:
    var kind := str(event.get("kind", ""))
    if not (_is_building_event(kind) or kind in ["building_removed", "road_changed"]): return
    var building_kind := str(event.get("building_kind", kind if kind in ["farm", "mine", "factory", "warehouse", "shop", "school", "hospital", "park"] else ""))
    for cell in event.get("cells", []):
        if not cell is Array or cell.size() != 2: continue
        var coord := Vector2i(int(cell[0]), int(cell[1]))
        if kind == "road_changed":
            _set_server_road(coord, true)
            continue
        if kind == "building_removed": server_cells.erase(coord)
        else: server_cells[coord] = {"kind":"building_created","building_kind":building_kind,"object_id":str(event.get("object_id", "")),"owner":str(event.get("owner", ""))}
        _redraw_chunk_at(coord)

func apply_chunk_snapshot(coord: Vector2i, cells: Array) -> void:
    for x in range(coord.x * CHUNK, (coord.x + 1) * CHUNK):
        for y in range(coord.y * CHUNK, (coord.y + 1) * CHUNK):
            server_cells.erase(Vector2i(x,y))
            roads.segments.erase(Vector2i(x,y))
    for cell in cells:
        if not cell is Dictionary: continue
        var c := Vector2i(int(cell.get("x", 0)), int(cell.get("y", 0)))
        var kind := str(cell.get("kind", ""))
        if kind == "road_changed":
            roads.segments[c] = true
        else:
            var bk := str(cell.get("building_kind", kind if kind in ["farm", "mine", "factory", "warehouse", "shop", "school", "hospital", "park"] else ""))
            server_cells[c] = {"kind":"building_created","building_kind":bk,"object_id":cell.get("object_id", ""),"owner":str(cell.get("owner", ""))}
    # Roads on the chunk border change the shape of roads in neighbouring chunks.
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            var n := coord + Vector2i(dx, dy)
            if active_chunks.has(n): active_chunks[n].queue_redraw()

func iso(x: float, y: float) -> Vector2:
    return Vector2((x - y) * TILE_W * 0.5, (x + y) * TILE_H * 0.5)

func cell_at(pos: Vector2) -> Vector2i:
    var x := pos.x / TILE_W + pos.y / TILE_H
    var y := pos.y / TILE_H - pos.x / TILE_W
    return Vector2i(floori(x), floori(y))

func _update_visible_chunks() -> void:
    if camera == null: return
    var rect := get_viewport_rect()
    var half := rect.size * 0.5 / camera.zoom
    var corners := [camera.position + Vector2(-half.x - 180, -half.y - 180), camera.position + Vector2(half.x + 180, -half.y - 180), camera.position + Vector2(-half.x - 180, half.y + 180), camera.position + Vector2(half.x + 180, half.y + 180)]
    var min_x := 2147483647
    var max_x := -2147483647
    var min_y := 2147483647
    var max_y := -2147483647
    for corner in corners:
        var cell := cell_at(corner)
        min_x = mini(min_x, cell.x)
        max_x = maxi(max_x, cell.x)
        min_y = mini(min_y, cell.y)
        max_y = maxi(max_y, cell.y)
    min_x = maxi(min_x - 2, -expansion_radius)
    max_x = mini(max_x + 2, expansion_radius)
    min_y = maxi(min_y - 2, -expansion_radius)
    max_y = mini(max_y + 2, expansion_radius)
    var needed: Dictionary = {}
    for cx in range(floori(float(min_x) / CHUNK), floori(float(max_x) / CHUNK) + 1):
        for cy in range(floori(float(min_y) / CHUNK), floori(float(max_y) / CHUNK) + 1):
            var coord := Vector2i(cx, cy)
            needed[coord] = true
            if not active_chunks.has(coord):
                var chunk = CHUNK_SCRIPT.new()
                chunk.world = self
                chunk.chunk_coord = coord
                add_child(chunk)
                active_chunks[coord] = chunk
    for coord in active_chunks.keys():
        if not needed.has(coord):
            active_chunks[coord].queue_free()
            active_chunks.erase(coord)

func _redraw_chunk_at(cell: Vector2i) -> void:
    var coord := Vector2i(floori(float(cell.x) / CHUNK), floori(float(cell.y) / CHUNK))
    if active_chunks.has(coord): active_chunks[coord].queue_redraw()

func _process(delta: float) -> void:
    var pan_alpha := 1.0 - exp(-PAN_RESPONSE * minf(delta, 0.1))
    var zoom_alpha := 1.0 - exp(-ZOOM_RESPONSE * minf(delta, 0.1))
    camera.position = camera.position.lerp(target_position, pan_alpha)
    var z := lerpf(camera.zoom.x, target_zoom, zoom_alpha)
    camera.zoom = Vector2(z, z)
    if camera.position != last_camera_position or camera.zoom.x != last_zoom:
        last_camera_position = camera.position
        last_zoom = camera.zoom.x
        _update_visible_chunks()

func _input(event: InputEvent) -> void:
    # _input also receives events consumed by GUI. Never select a world tile
    # when the user presses or releases a construction/HUD button.
    if event is InputEventScreenTouch:
        if event.pressed and get_parent().is_world_ui_point(event.position):
            ui_touch_indices[event.index] = true
            return
        if ui_touch_indices.has(event.index):
            if not event.pressed:
                ui_touch_indices.erase(event.index)
            return
    if event is InputEventScreenDrag and ui_touch_indices.has(event.index):
        return
    if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
        if event.pressed:
            ui_mouse_press = get_parent().is_world_ui_point(event.position)
            if ui_mouse_press: return
        elif ui_mouse_press:
            ui_mouse_press = false
            return
    if event is InputEventMouseMotion and ui_mouse_press:
        return
    if event is InputEventScreenTouch:
        if event.pressed:
            touch_points[event.index] = event.position
            if touch_points.size() == 1: moved = false
            if touch_points.size() == 2:
                var pair := touch_points.values()
                pinch_distance = pair[0].distance_to(pair[1])
                last_pinch_midpoint = (pair[0] + pair[1]) * 0.5
                moved = true
        else:
            if touch_points.size() == 1 and not moved and not get_parent().is_world_ui_point(event.position):
                select_screen(event.position)
            touch_points.erase(event.index)
            pinch_distance = 0.0
            if touch_points.size() > 0: moved = true
    elif event is InputEventScreenDrag:
        var old: Vector2 = touch_points.get(event.index, event.position - event.relative)
        touch_points[event.index] = event.position
        if touch_points.size() == 1:
            target_position -= (event.position - old) * PAN_SENSITIVITY / target_zoom
            moved = true
        elif touch_points.size() == 2:
            var points := touch_points.values()
            var dist: float = points[0].distance_to(points[1])
            if pinch_distance > 0.0:
                var ratio := dist / pinch_distance
                set_zoom(target_zoom * pow(ratio, ZOOM_SENSITIVITY))
            var midpoint: Vector2 = (points[0] + points[1]) * 0.5
            target_position -= (midpoint - last_pinch_midpoint) * PAN_SENSITIVITY / target_zoom
            last_pinch_midpoint = midpoint
            pinch_distance = dist
            moved = true
        clamp_camera()
    elif event is InputEventMouseButton:
        if event.button_index == MOUSE_BUTTON_WHEEL_UP and event.pressed:
            set_zoom(target_zoom * 1.12)
        elif event.button_index == MOUSE_BUTTON_WHEEL_DOWN and event.pressed:
            set_zoom(target_zoom / 1.12)
        elif event.button_index == MOUSE_BUTTON_LEFT:
            dragging = event.pressed
            if dragging:
                moved = false
                last_mouse = event.position
            elif not moved and not get_parent().is_world_ui_point(event.position):
                select_screen(event.position)
    elif event is InputEventMouseMotion and dragging:
        target_position -= event.relative * PAN_SENSITIVITY / target_zoom
        moved = true
        clamp_camera()

func select_screen(pos: Vector2) -> void:
    # Convert viewport touch using the actual rendered canvas transform.
    var world_pos: Vector2 = get_canvas_transform().affine_inverse() * pos
    # Isometric cells are diamonds centred on iso(x, y), not floor-based squares.
    var fractional_x: float = world_pos.x / TILE_W + world_pos.y / TILE_H
    var fractional_y: float = world_pos.y / TILE_H - world_pos.x / TILE_W
    var cell := Vector2i(roundi(fractional_x), roundi(fractional_y))
    if absi(cell.x) <= expansion_radius and absi(cell.y) <= expansion_radius:
        var previous := selected
        selected = cell
        _redraw_build_area(previous, build_size(build_type))
        _redraw_build_area(cell, build_size(build_type))
        _redraw_chunk_at(previous)
        _redraw_chunk_at(cell)
        get_tree().call_group("world_hud", "set_selection", cell)
        if not build_type.is_empty():
            get_tree().call_group("world_hud", "show_build_preview", preview_build(cell))

func set_zoom(z: float) -> void:
    var v := clampf(z, 0.45, 2.3)
    target_zoom = v
    clamp_camera()

func clamp_camera() -> void:
    # Exploration camera can move beyond discovered chunks; no fixed world edge.
    target_position.x = clampf(target_position.x, -500000.0, 500000.0)
    target_position.y = clampf(target_position.y, -500000.0, 500000.0)

func expand_city(chunks: int = 1) -> void:
    expansion_radius += maxi(chunks, 1) * CHUNK
    _update_visible_chunks()
    for chunk in active_chunks.values(): chunk.queue_redraw()

func preview_access_road(site: Vector2i) -> Array[Vector2i]:
    return roads.connect_site(site)

func commit_access_road(site: Vector2i) -> bool:
    # Visual sandbox only; server authority required before gameplay.
    var path: Array[Vector2i] = preview_access_road(site)
    var accepted: bool = roads.add_path(path)
    if accepted:
        for cell in path:
            for affected in preload("res://road_topology.gd").affected_cells(cell):
                _redraw_chunk_at(affected)
    return accepted
func build_size(kind: String) -> Vector2i:
    match kind:
        "farm": return Vector2i(2, 2)
        "mine": return Vector2i(2, 3)
        "factory": return Vector2i(3, 2)
        "warehouse": return Vector2i(3, 3)
        "shop": return Vector2i(2, 2)
        "school": return Vector2i(3, 2)
        "hospital": return Vector2i(3, 3)
        "park": return Vector2i(2, 2)
    return Vector2i.ZERO

func preview_build(cell: Vector2i) -> Dictionary:
    if build_type.is_empty(): return {"ok": false, "reason": "no_build_mode"}
    return planner.preview(cell, build_size(build_type), roads, self)

func choose_build(kind: String) -> void:
    build_type = kind
    if selected != Vector2i(-1, -1):
        get_tree().call_group("world_hud", "show_build_preview", preview_build(selected))
        _redraw_build_area(selected, build_size(build_type))

func cancel_build() -> void:
    var old_size := build_size(build_type)
    build_type = ""
    _redraw_build_area(selected, old_size)

func place_building() -> Dictionary:
    if build_type.is_empty() or selected == Vector2i(-1, -1):
        return {"ok": false, "reason": "no_selection"}
    var result := preview_build(selected)
    if not result.get("ok", false): return result
    build_counter += 1
    var object_id := "sandbox_%d" % build_counter
    var cells: Array[Vector2i] = result["cells"]
    if not planner.reserve_preview(cells, object_id):
        return {"ok": false, "reason": "occupied"}
    building_records[object_id] = {"kind": build_type, "origin": selected, "cells": cells}
    for cell in cells: _redraw_chunk_at(cell)
    # Auto-build the access road to the nearest existing road.
    var access: Array[Vector2i] = result.get("access", [] as Array[Vector2i])
    if not access.is_empty() and roads.add_path(access):
        for road_cell in access:
            for affected in preload("res://road_topology.gd").affected_cells(road_cell):
                _redraw_chunk_at(affected)
    return {"ok": true, "reason": "sandbox_only", "object_id": object_id, "road_cells": access.size()}

func _redraw_build_area(origin: Vector2i, size: Vector2i) -> void:
    for cell in planner.footprint(origin, size):
        _redraw_chunk_at(cell)

func building_info(cell: Vector2i) -> Dictionary:
    """Server building on a cell: {kind, object_id, owner}, or an empty dictionary."""
    if not server_cells.has(cell): return {}
    var c: Dictionary = server_cells[cell]
    if str(c.get("object_id", "")) == "": return {}
    return {"kind": str(c.get("building_kind", "")), "object_id": str(c.get("object_id", "")), "owner": str(c.get("owner", ""))}

func building_at(cell: Vector2i) -> String:
    if server_cells.has(cell):
        return str(server_cells[cell].get("building_kind", ""))
    var object_id: String = str(planner.occupied.get(cell, ""))
    if building_records.has(object_id):
        return str(building_records[object_id].get("kind", ""))
    return ""
