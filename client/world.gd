extends Node2D
## Deterministic visual-only isometric world. No server authority or gameplay state.
const TILE_W := 96.0
const TILE_H := 48.0
const CHUNK := 12
const WORLD := 144
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
    queue_redraw()

func cell_kind(x: int, y: int) -> int:
    # Integer-only hash: independent of call order and frame rate.
    var h := (x * 73856093) ^ (y * 19349663) ^ SEED
    h = (h ^ (h >> 13)) * 1274126177
    var n := posmod(h ^ (h >> 16), 100)
    if x % 19 == 0 or y % 23 == 0:
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

func _draw() -> void:
    if camera == null:
        return
    var rect := get_viewport_rect()
    var half := rect.size * 0.5 / camera.zoom
    var a := cell_at(camera.position - half - Vector2(200, 200))
    var b := cell_at(camera.position + half + Vector2(200, 200))
    var c := cell_at(camera.position + Vector2(-half.x, half.y) + Vector2(-200, 200))
    var d := cell_at(camera.position + Vector2(half.x, -half.y) + Vector2(200, -200))
    var min_x: int = clampi(mini(mini(a.x, b.x), mini(c.x, d.x)) - 2, 0, WORLD - 1)
    var max_x: int = clampi(maxi(maxi(a.x, b.x), maxi(c.x, d.x)) + 2, 0, WORLD - 1)
    var min_y: int = clampi(mini(mini(a.y, b.y), mini(c.y, d.y)) - 2, 0, WORLD - 1)
    var max_y: int = clampi(maxi(maxi(a.y, b.y), maxi(c.y, d.y)) + 2, 0, WORLD - 1)
    # Iterate visible chunk ranges, draw only visible cells.
    for cx in range(min_x / CHUNK, max_x / CHUNK + 1):
        for cy in range(min_y / CHUNK, max_y / CHUNK + 1):
            for x in range(maxi(min_x, cx * CHUNK), mini(max_x + 1, (cx + 1) * CHUNK)):
                for y in range(maxi(min_y, cy * CHUNK), mini(max_y + 1, (cy + 1) * CHUNK)):
                    var p := iso(float(x), float(y))
                    var pts := PackedVector2Array([p + Vector2(0, -TILE_H / 2), p + Vector2(TILE_W / 2, 0), p + Vector2(0, TILE_H / 2), p + Vector2(-TILE_W / 2, 0)])
                    var kind := cell_kind(x, y)
                    draw_colored_polygon(pts, COLORS[kind])
                    draw_polyline(PackedVector2Array([pts[0], pts[1], pts[2], pts[3], pts[0]]), Color(0.10, 0.19, 0.16, 0.30), 1.0)
                    if kind == 5:
                        draw_circle(p + Vector2(0, -10), 10, Color("#305e43"))
                        draw_circle(p + Vector2(3, -15), 7, Color("#477b4d"))
                    if selected == Vector2i(x, y):
                        draw_polyline(PackedVector2Array([pts[0], pts[1], pts[2], pts[3], pts[0]]), Color("#f8d46a"), 3.0)

func _process(_delta: float) -> void:
    queue_redraw()

func _unhandled_input(event: InputEvent) -> void:
    if event is InputEventScreenTouch:
        if event.pressed:
            touch_points[event.index] = event.position
            moved = false
        else:
            if touch_points.size() == 1 and not moved:
                select_screen(event.position)
            touch_points.erase(event.index)
            pinch_distance = 0.0
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
    if cell.x >= 0 and cell.y >= 0 and cell.x < WORLD and cell.y < WORLD:
        selected = cell
        get_tree().call_group("world_hud", "set_selection", cell)

func set_zoom(z: float) -> void:
    var v := clampf(z, 0.45, 2.3)
    camera.zoom = Vector2(v, v)
    clamp_camera()

func clamp_camera() -> void:
    camera.position.x = clampf(camera.position.x, -WORLD * TILE_W * 0.48, WORLD * TILE_W * 0.48)
    camera.position.y = clampf(camera.position.y, -100.0, WORLD * TILE_H)
