extends Control
signal viewport_moved(center: Vector2i, radius: int)
signal parcel_tapped(px: int, py: int)
const Gen = preload("res://world/generator.gd")
const CELL_PIXELS := 24.0
const TILE_COLORS := {
    "ground": Color("497659"), "water": Color("2b718c"), "tree": Color("2a6343"),
    "center": Color("c7b888"), "residential": Color("7caa76"),
    "industrial": Color("a38b67"), "free": Color("568564")
}
var stream: Node
var center := Vector2.ZERO
var zoom := 1.0
var selected := Vector2i(2147483647,2147483647)
var tiles: Dictionary = {}
var touches: Dictionary = {}
var start_touch: Dictionary = {}
var drag_distance := 0.0
var mouse_down := false
var velocity := Vector2.ZERO
var _last_gesture := Vector2.ZERO
var _last_dist := 0.0
var _last_view := Vector2i(999999,999999)
var _last_radius := 0
var _pulse := 0.0

func attach(source: Node) -> void:
    stream = source
    stream.chunk_ready.connect(_on_chunk)
    stream.chunk_removed.connect(_on_removed)
    stream.parcels_ready.connect(func(_key: Vector2i, _items: Array): queue_redraw())

func _ready() -> void:
    mouse_filter = Control.MOUSE_FILTER_STOP
    clip_contents = true
    resized.connect(_refresh_visibility)
    set_process(true)

func focus(cell: Vector2i) -> void:
    _last_radius = -1
    center = Vector2(cell)
    velocity = Vector2.ZERO
    _refresh_visibility()
    queue_redraw()

func _cell_size() -> float:
    return CELL_PIXELS * zoom

func _screen_to_cell(point: Vector2) -> Vector2i:
    var tile := _cell_size()
    return Vector2i(floori(center.x + (point.x - size.x / 2.0) / tile),floori(center.y + (point.y - size.y / 2.0) / tile))

func _origin_of_cell(x: int,y: int) -> Vector2:
    return Vector2(size.x / 2.0 + (float(x) - center.x) * _cell_size(), size.y / 2.0 + (float(y) - center.y) * _cell_size())

func _radius() -> int:
    return clampi(ceili(maxf(size.x,size.y) / (24.0 * zoom * 12.0 * 2.0)) + 1, 2, 6)

func _refresh_visibility() -> void:
    if stream == null or size.x <= 0 or size.y <= 0:
        return
    var at := Vector2i(floori(center.x), floori(center.y))
    var chunk := Vector2i(Gen.floor_div(at.x,12), Gen.floor_div(at.y,12))
    var radius := _radius()
    if chunk == _last_view and radius == _last_radius:
        return
    _last_view = chunk
    _last_radius = radius
    stream.update_center(at, radius)
    viewport_moved.emit(at, radius)

func _process(delta: float) -> void:
    if not visible:
        return
    if touches.is_empty() and not mouse_down and velocity.length() > 0.005:
        center += velocity * delta
        velocity *= exp(-6.0 * delta)
        _refresh_visibility()
        queue_redraw()

func _on_chunk(key: Vector2i, snapshot: Dictionary) -> void:
    var image := Image.create(12,12,false,Image.FORMAT_RGBA8)
    var terrain: Array = snapshot.get("terrain", [])
    var zones: Array = snapshot.get("zones", [])
    var roads: Array = snapshot.get("roads", [])
    if terrain.size() != 12:
        return
    for y in range(12):
        for x in range(12):
            var t: String = str(terrain[y][x])
            var zone_name := "free"
            if zones.size() > y and zones[y].size() > x:
                zone_name = str(zones[y][x])
            var color: Color = TILE_COLORS.get(t, TILE_COLORS["ground"])
            if t == "ground":
                color = color.lerp(TILE_COLORS.get(zone_name,TILE_COLORS["free"]),0.42)
            if roads.size() > y and roads[y].size() > x and bool(roads[y][x]):
                color = Color("afab94")
            image.set_pixel(x,y,color)
    tiles[key] = ImageTexture.create_from_image(image)
    queue_redraw()

func _on_removed(key: Vector2i) -> void:
    tiles.erase(key)
    queue_redraw()

func _draw() -> void:
    draw_rect(Rect2(Vector2.ZERO,size),Color("203c30"))
    var tile := _cell_size()
    for key in tiles:
        var origin := _origin_of_cell(key.x*12,key.y*12)
        var rect := Rect2(origin,Vector2(tile*12.0,tile*12.0))
        if not rect.intersects(Rect2(Vector2.ZERO,size)):
            continue
        draw_texture_rect(tiles[key],rect,false)
        var border_color := Color(0.8,0.94,0.8,0.19)
        for i in range(3):
            var x := origin.x + i*6.0*tile
            var y := origin.y + i*6.0*tile
            draw_line(Vector2(x,origin.y),Vector2(x,origin.y+12.0*tile),border_color,1.0)
            draw_line(Vector2(origin.x,y),Vector2(origin.x+12.0*tile,y),border_color,1.0)
    if selected.x != 2147483647:
        var p := _origin_of_cell(selected.x*6,selected.y*6)
        draw_rect(Rect2(p,Vector2(tile*6,tile*6)),Color("f5efb9"),false,maxf(2.0,zoom*2.0))

func _zoom_at(new_zoom: float, point: Vector2) -> void:
    var old_zoom := zoom
    zoom = clampf(new_zoom,0.55,3.0)
    if is_equal_approx(old_zoom,zoom):
        return
    var v := point-size/2.0
    center += v * (1.0/(CELL_PIXELS*old_zoom)-1.0/(CELL_PIXELS*zoom))
    _last_radius = -1
    _refresh_visibility()
    queue_redraw()

func _tap(point: Vector2) -> void:
    var cell := _screen_to_cell(point)
    var px := Gen.floor_div(cell.x,6)
    var py := Gen.floor_div(cell.y,6)
    selected = Vector2i(px,py)
    parcel_tapped.emit(px,py)
    queue_redraw()

func _gui_input(event: InputEvent) -> void:
    if event is InputEventScreenTouch:
        if event.pressed:
            touches[event.index] = event.position
            start_touch[event.index] = event.position
            velocity = Vector2.ZERO
            if touches.size() == 2:
                var points := touches.values()
                _last_dist = (points[0]-points[1]).length()
                _last_gesture = (points[0]+points[1])*0.5
        else:
            if touches.size()==1 and drag_distance < 12.0:
                _tap(event.position)
            touches.erase(event.index)
            start_touch.erase(event.index)
            drag_distance = 0.0
            _last_dist = 0.0
        accept_event()
    elif event is InputEventScreenDrag:
        if not touches.has(event.index):
            return
        var previous: Vector2 = touches[event.index]
        touches[event.index] = event.position
        drag_distance += (event.position-previous).length()
        if touches.size() >= 2:
            var points := touches.values()
            var dist: float = (points[0]-points[1]).length()
            var mid: Vector2 = (points[0]+points[1])*0.5
            if _last_dist > 1.0:
                _zoom_at(zoom*dist/_last_dist,mid)
            _last_dist = dist
            _last_gesture = mid
        else:
            var motion: Vector2 = event.position-previous
            center -= motion/_cell_size()
            velocity = -motion/_cell_size()*30.0
            _refresh_visibility()
            queue_redraw()
        accept_event()
    elif event is InputEventMouseButton:
        if event.button_index == MOUSE_BUTTON_WHEEL_UP and event.pressed:
            _zoom_at(zoom*1.14,event.position)
            accept_event()
        elif event.button_index == MOUSE_BUTTON_WHEEL_DOWN and event.pressed:
            _zoom_at(zoom/1.14,event.position)
            accept_event()
        elif event.button_index == MOUSE_BUTTON_LEFT:
            mouse_down = event.pressed
            if event.pressed:
                _last_gesture = event.position
                drag_distance = 0.0
                velocity = Vector2.ZERO
            elif drag_distance < 12.0:
                _tap(event.position)
            accept_event()
    elif event is InputEventMouseMotion and mouse_down:
        var movement: Vector2 = event.position-_last_gesture
        _last_gesture = event.position
        drag_distance += movement.length()
        center -= movement/_cell_size()
        velocity = -movement/_cell_size()*30.0
        _refresh_visibility()
        queue_redraw()
        accept_event()
