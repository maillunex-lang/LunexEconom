extends Node2D
## Deterministic visual-only isometric world. No server authority or gameplay state.
const TILE_W := 96.0
const TILE_H := 48.0
const CHUNK := 12
const ROAD_SCRIPT = preload("res://road_network.gd")
const MAX_VISIBLE_CELLS := 4500
const CHUNK_SCRIPT = preload("res://chunk_renderer.gd")
var active_chunks: Dictionary = {}
var last_camera_position := Vector2.INF
var last_zoom := -1.0
var roads = ROAD_SCRIPT.new()
var expansion_radius := 48
const SEED := 18273
const COLORS := [
    Color("#63865b"), Color("#72915e"), Color("#8ca66a"),
    Color("#b6a36d"), Color("#527f8d"), Color("#547c54")
]
var camera: Camera2D
var selected := Vector2i(-1, -1)
var touch_points: Dictionary = {}
var dragging := false
var moved := false
var pinch_distance := 0.0
var last_mouse := Vector2.ZERO

func _ready() -> void:
    camera = Camera2D.new()
    camera.name = "WorldCamera"
    camera.enabled = true
    camera.position = Vector2(0, 300)
    camera.zoom = Vector2.ONE
    add_child(camera)
    _update_visible_chunks()

func cell_kind(x: int, y: int) -> int:
    # Integer-only hash: independent of call order and frame rate.
    var h := (x * 73856093) ^ (y * 19349663) ^ SEED
    h = (h ^ (h >> 13)) * 1274126177
    var n := posmod(h ^ (h >> 16), 100)
    if roads.is_road(Vector2i(x, y)):
        return 3 # roads
    if n < 8:
        return 4 # water
    if n < 24:
        return 5 # trees
    return n % 3

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

func _process(_delta: float) -> void:
    if camera.position != last_camera_position or camera.zoom.x != last_zoom:
        last_camera_position = camera.position
        last_zoom = camera.zoom.x
        _update_visible_chunks()

func _unhandled_input(event: InputEvent) -> void:
    if event is InputEventScreenTouch:
        if event.pressed:
            touch_points[event.index] = event.position
            if touch_points.size() == 1: moved = false
            if touch_points.size() == 2:
                var pair := touch_points.values()
                pinch_distance = pair[0].distance_to(pair[1])
                moved = true
        else:
            if touch_points.size() == 1 and not moved:
                select_screen(event.position)
            touch_points.erase(event.index)
            pinch_distance = 0.0
            if touch_points.size() > 0: moved = true
    elif event is InputEventScreenDrag:
        var old: Vector2 = touch_points.get(event.index, event.position - event.relative)
        touch_points[event.index] = event.position
        if touch_points.size() == 1:
            camera.position -= (event.position - old) / camera.zoom
            moved = true
        elif touch_points.size() == 2:
            var points := touch_points.values()
            var dist: float = points[0].distance_to(points[1])
            if pinch_distance > 0.0:
                set_zoom(camera.zoom.x * dist / pinch_distance)
            pinch_distance = dist
            moved = true
        clamp_camera()
    elif event is InputEventMouseButton:
        if event.button_index == MOUSE_BUTTON_WHEEL_UP and event.pressed:
            set_zoom(camera.zoom.x * 1.12)
        elif event.button_index == MOUSE_BUTTON_WHEEL_DOWN and event.pressed:
            set_zoom(camera.zoom.x / 1.12)
        elif event.button_index == MOUSE_BUTTON_LEFT:
            dragging = event.pressed
            if dragging:
                moved = false
                last_mouse = event.position
            elif not moved:
                select_screen(event.position)
    elif event is InputEventMouseMotion and dragging:
        camera.position -= event.relative / camera.zoom
        moved = true
        clamp_camera()

func select_screen(pos: Vector2) -> void:
    var local := camera.get_screen_transform().affine_inverse() * pos
    var cell := cell_at(local)
    if absi(cell.x) <= expansion_radius and absi(cell.y) <= expansion_radius:
        var previous := selected
        selected = cell
        _redraw_chunk_at(previous)
        _redraw_chunk_at(cell)
        get_tree().call_group("world_hud", "set_selection", cell)

func set_zoom(z: float) -> void:
    var v := clampf(z, 0.45, 2.3)
    camera.zoom = Vector2(v, v)
    clamp_camera()

func clamp_camera() -> void:
    # Exploration camera can move beyond discovered chunks; no fixed world edge.
    camera.position.x = clampf(camera.position.x, -500000.0, 500000.0)
    camera.position.y = clampf(camera.position.y, -500000.0, 500000.0)

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
        for cell in path: _redraw_chunk_at(cell)
    return accepted