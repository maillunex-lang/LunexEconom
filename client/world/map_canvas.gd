extends Control
signal viewport_moved(center: Vector2i, radius: int)
signal parcel_tapped(px: int, py: int)
signal cell_tapped(cell: Vector2i)
const Gen = preload("res://world/generator.gd")
const ChunkSprite = preload("res://world/chunk_sprite.gd")
const CELL_PIXELS := 24.0
const TEXTURE_LIMIT := 96
const TILE_COLORS := {
    "ground":Color("497659"),"water":Color("2b718c"),"tree":Color("2a6343"),
    "center":Color("c7b888"),"residential":Color("7caa76"),
    "industrial":Color("a38b67"),"free":Color("568564")
}
var stream: Node
var center := Vector2.ZERO
var zoom := 1.0
var selected := Vector2i(2147483647,2147483647)
var tiles: Dictionary = {}
var building_cells: Dictionary = {}
var enterprise_info: Dictionary = {}
var preview: Dictionary = {}
var road_preview: Array[Vector2i] = []
var road_mode := false
var touches: Dictionary = {}
var start_touch: Dictionary = {}
var drag_distance := 0.0
var mouse_down := false
var velocity := Vector2.ZERO
var _last_gesture := Vector2.ZERO
var _last_dist := 0.0
var _pinching := false
var _last_view := Vector2i(999999,999999)
var _last_radius := 0
var _layer: Node2D
var _sprites: Dictionary = {}
var _texture_lru: Dictionary = {}
var _touch_clock := 0
var texture_builds := 0

func attach(source: Node) -> void:
    stream = source
    stream.chunk_ready.connect(_on_chunk)
    stream.chunk_removed.connect(_on_removed)
    stream.object_delta.connect(_on_object_delta)
    stream.parcels_ready.connect(func(_key: Vector2i,_items: Array):
        if selected.x != 2147483647:
            queue_redraw())

func _ready() -> void:
    mouse_filter = Control.MOUSE_FILTER_STOP
    clip_contents = true
    _layer = Node2D.new()
    _layer.name = "ChunkLayer"
    _layer.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
    add_child(_layer)
    resized.connect(_on_resized)
    set_process(true)
    _update_transform()

func _on_resized() -> void:
    _update_transform()
    _refresh_visibility()
    if _overlay_active():
        queue_redraw()

func _overlay_active() -> bool:
    return selected.x != 2147483647 or not preview.is_empty() or not road_preview.is_empty()

func _update_transform() -> void:
    if _layer == null:
        return
    _layer.scale = Vector2.ONE * _cell_size()
    _layer.position = size * 0.5 - center * _cell_size()

func focus(cell: Vector2i) -> void:
    center = Vector2(cell)
    velocity = Vector2.ZERO
    _update_transform()
    _refresh_visibility()
    if _overlay_active():
        queue_redraw()

func _cell_size() -> float:
    return CELL_PIXELS * zoom

func _screen_to_cell(point: Vector2) -> Vector2i:
    var tile := _cell_size()
    return Vector2i(floori(center.x+(point.x-size.x/2.0)/tile),
        floori(center.y+(point.y-size.y/2.0)/tile))

func _origin_of_cell(x: int, y: int) -> Vector2:
    return Vector2(size.x/2.0+(float(x)-center.x)*_cell_size(),
        size.y/2.0+(float(y)-center.y)*_cell_size())

func _radius() -> int:
    # One additional full ring beyond the visible rectangle.
    return clampi(ceili(maxf(size.x,size.y)/(CELL_PIXELS*zoom*12.0*2.0))+2,2,6)

func _refresh_visibility() -> void:
    if stream == null or size.x <= 0 or size.y <= 0:
        return
    var at := Vector2i(floori(center.x),floori(center.y))
    var chunk := Vector2i(Gen.floor_div(at.x,12),Gen.floor_div(at.y,12))
    var radius := _radius()
    if chunk == _last_view and radius == _last_radius:
        return
    _last_view = chunk
    _last_radius = radius
    stream.update_center(at,radius)
    viewport_moved.emit(at,radius)

func _process(delta: float) -> void:
    if not visible:
        return
    if touches.is_empty() and not mouse_down and velocity.length() > 0.005:
        center += velocity * minf(delta,0.05)
        velocity *= exp(-6.0*minf(delta,0.05))
        if velocity.length() < 0.005:
            velocity = Vector2.ZERO
        _update_transform()
        _refresh_visibility()
        if _overlay_active():
            queue_redraw()

func _texture_for(key: Vector2i, snapshot: Dictionary) -> Texture2D:
    var version := int(snapshot.get("version", -1))
    _touch_clock += 1
    var cached: Dictionary = _texture_lru.get(key, {})
    if int(cached.get("version", -999999)) == version and cached.has("texture"):
        cached["used"] = _touch_clock
        _texture_lru[key] = cached
        return cached["texture"]
    var image := Image.create(12,12,false,Image.FORMAT_RGBA8)
    var terrain: Array = snapshot.get("terrain", [])
    var zones: Array = snapshot.get("zones", [])
    var roads: Array = snapshot.get("roads", [])
    if terrain.size() != 12:
        return null
    for y in range(12):
        for x in range(12):
            var name := str(terrain[y][x])
            var zone_name := "free"
            if zones.size()>y and zones[y].size()>x:
                zone_name = str(zones[y][x])
            var color: Color = TILE_COLORS.get(name,TILE_COLORS["ground"])
            if name == "ground":
                color = color.lerp(TILE_COLORS.get(zone_name,TILE_COLORS["free"]),0.42)
            if roads.size()>y and roads[y].size()>x and bool(roads[y][x]):
                color = Color("afab94")
            image.set_pixel(x,y,color)
    var tile := ImageTexture.create_from_image(image)
    texture_builds += 1
    _texture_lru[key] = {"version":version,"texture":tile,"used":_touch_clock}
    if _texture_lru.size()>TEXTURE_LIMIT:
        var oldest := 9223372036854775807
        var victim: Variant = null
        for candidate in _texture_lru:
            if candidate == key:
                continue
            var age := int(_texture_lru[candidate]["used"])
            if age<oldest:
                oldest=age
                victim=candidate
        if victim != null:
            _texture_lru.erase(victim)
    return tile

func _on_chunk(key: Vector2i, snapshot: Dictionary) -> void:
    var tile := _texture_for(key,snapshot)
    if tile == null:
        return
    tiles[key] = tile
    var buildings: Array = snapshot.get("buildings", [])
    var cells: Array = []
    for cy in range(buildings.size()):
        for cx in range(buildings[cy].size()):
            var ref: Variant = buildings[cy][cx]
            if ref != null and str(ref) != "":
                cells.append({"x":key.x*12+cx,"y":key.y*12+cy,"ref":str(ref)})
    building_cells[key] = cells
    if _layer == null:
        return
    var sprite: Node2D = _sprites.get(key)
    if sprite == null:
        sprite = ChunkSprite.new()
        sprite.position = Vector2(key.x*12,key.y*12)
        _sprites[key] = sprite
        _layer.add_child(sprite)
    sprite.set_content(tile,cells,enterprise_info)

func _on_object_delta(event: Dictionary) -> void:
    var payload: Dictionary = event.get("payload",{})
    var kind := str(event.get("kind",""))
    var object_data: Variant = event.get("object",payload.get("object"))
    var impacted: Dictionary = {}
    if kind == "road_build":
        for cell in payload.get("cells",[]):
            if not cell is Array or cell.size()<2:
                continue
            var x := int(cell[0])
            var y := int(cell[1])
            var key := Vector2i(Gen.floor_div(x,12),Gen.floor_div(y,12))
            impacted[key] = true
            if not stream.chunks.has(key):
                continue
            var snapshot: Dictionary = stream.chunks[key]
            var roads: Array = snapshot.get("roads",[])
            var local_y := posmod(y,12)
            var local_x := posmod(x,12)
            if local_y<roads.size() and local_x<roads[local_y].size():
                roads[local_y][local_x] = not bool(event.get("removed",payload.get("removed",false)))
                # Texture changes only for the touched chunk, never neighbours.
                _texture_lru.erase(key)
                _on_chunk(key,snapshot)
    elif object_data is Dictionary:
        var object_id := str(object_data.get("object_id",""))
        var x := int(object_data.get("x",0))
        var y := int(object_data.get("y",0))
        var w := int(object_data.get("w",1))
        var h := int(object_data.get("h",1))
        if w<1 or h<1 or w*h>48:
            return
        for yy in range(y,y+h):
            for xx in range(x,x+w):
                var key := Vector2i(Gen.floor_div(xx,12),Gen.floor_div(yy,12))
                impacted[key] = true
                if not _sprites.has(key):
                    continue
                var sprite: Node2D = _sprites[key]
                if kind == "demolition":
                    sprite.remove_building_cell(object_id,xx,yy)
                else:
                    sprite.update_building_cell(object_id,xx,yy,object_data)
    elif kind == "land_buy":
        var px := int(payload.get("px",0))
        var py := int(payload.get("py",0))
        var key := Vector2i(Gen.floor_div(px,2),Gen.floor_div(py,2))
        impacted[key] = true
    for key in impacted:
        if stream.chunks.has(key):
            # Only the authoritative current viewport changes. Snapshot
            # versions are advanced without recreating unaffected textures.
            stream.chunks[key]["version"] = maxi(int(stream.chunks[key].get("version",0)),int(event.get("version",0)))

func refresh_buildings() -> void:
    for key in _sprites:
        _sprites[key].set_content(tiles[key],building_cells.get(key,[]),enterprise_info)

func _on_removed(key: Vector2i) -> void:
    tiles.erase(key)
    building_cells.erase(key)
    var sprite: Node2D = _sprites.get(key)
    if sprite != null:
        sprite.queue_free()
        _sprites.erase(key)

func _draw() -> void:
    # This overlay is tiny. All terrain and buildings are cached child CanvasItems.
    if not preview.is_empty():
        var origin := _origin_of_cell(int(preview.get("x",0)),int(preview.get("y",0)))
        var footprint := Vector2(int(preview.get("width",1)),int(preview.get("height",1)))*_cell_size()
        draw_rect(Rect2(origin,footprint),Color("f7e2a4",0.25),true)
        draw_rect(Rect2(origin,footprint),Color("fff2c2"),false,2.0)
    for cell in road_preview:
        var pos := _origin_of_cell(cell.x,cell.y)
        draw_rect(Rect2(pos,Vector2.ONE*_cell_size()),Color("6ab7d2",0.65),true)
        draw_rect(Rect2(pos,Vector2.ONE*_cell_size()),Color("e8f9ff"),false,2.0)
    if selected.x != 2147483647:
        var p := _origin_of_cell(selected.x*6,selected.y*6)
        draw_rect(Rect2(p,Vector2.ONE*_cell_size()*6.0),
            Color("f5efb9"),false,maxf(2.0,zoom*2.0))

func _zoom_at(next_zoom: float, point: Vector2) -> void:
    var old := zoom
    zoom = clampf(next_zoom,0.55,3.0)
    if is_equal_approx(old,zoom):
        return
    var v := point-size/2.0
    center += v * (1.0/(CELL_PIXELS*old)-1.0/(CELL_PIXELS*zoom))
    _update_transform()
    _refresh_visibility()
    if _overlay_active():
        queue_redraw()

func _tap(point: Vector2) -> void:
    var cell := _screen_to_cell(point)
    if road_mode:
        cell_tapped.emit(cell)
        return
    selected = Vector2i(Gen.floor_div(cell.x,6),Gen.floor_div(cell.y,6))
    parcel_tapped.emit(selected.x,selected.y)
    queue_redraw()

func _gui_input(event: InputEvent) -> void:
    if event is InputEventScreenTouch:
        if event.pressed:
            touches[event.index] = event.position
            start_touch[event.index] = event.position
            velocity = Vector2.ZERO
            if touches.size()==2:
                _pinching = true
                var pts := touches.values()
                _last_dist = (pts[0]-pts[1]).length()
                _last_gesture = (pts[0]+pts[1])*0.5
        else:
            if touches.size()==1 and drag_distance<12.0 and not _pinching:
                _tap(event.position)
            touches.erase(event.index)
            start_touch.erase(event.index)
            if touches.is_empty():
                _pinching = false
                drag_distance = 0.0
            _last_dist = 0.0
        accept_event()
    elif event is InputEventScreenDrag:
        if not touches.has(event.index):
            return
        var previous: Vector2 = touches[event.index]
        touches[event.index] = event.position
        drag_distance += (event.position-previous).length()
        if touches.size()>=2:
            var pts := touches.values()
            var dist: float = (pts[0]-pts[1]).length()
            var mid: Vector2 = (pts[0]+pts[1])*0.5
            if _last_dist>1.0:
                # Damp and clamp sudden pinch samples; pivot under both fingers.
                var ratio := clampf(pow(dist/_last_dist,0.65),0.89,1.11)
                _zoom_at(zoom*ratio,mid)
            center -= (mid-_last_gesture)/_cell_size()
            _last_dist=dist
            _last_gesture=mid
            _update_transform()
            _refresh_visibility()
            if _overlay_active():
                queue_redraw()
        else:
            var motion: Vector2 = event.position-previous
            center -= motion/_cell_size()
            velocity = (-motion/_cell_size()*30.0).limit_length(140.0)
            _update_transform()
            _refresh_visibility()
            if _overlay_active():
                queue_redraw()
        accept_event()
    elif event is InputEventMouseButton:
        if event.button_index==MOUSE_BUTTON_WHEEL_UP and event.pressed:
            _zoom_at(zoom*1.14,event.position)
            accept_event()
        elif event.button_index==MOUSE_BUTTON_WHEEL_DOWN and event.pressed:
            _zoom_at(zoom/1.14,event.position)
            accept_event()
        elif event.button_index==MOUSE_BUTTON_LEFT:
            mouse_down=event.pressed
            if event.pressed:
                _last_gesture=event.position
                drag_distance=0.0
                velocity=Vector2.ZERO
            elif drag_distance<12.0:
                _tap(event.position)
            accept_event()
    elif event is InputEventMouseMotion and mouse_down:
        var motion: Vector2=event.position-_last_gesture
        _last_gesture=event.position
        drag_distance += motion.length()
        center -= motion/_cell_size()
        velocity = (-motion/_cell_size()*30.0).limit_length(140.0)
        _update_transform()
        _refresh_visibility()
        if _overlay_active():
            queue_redraw()
        accept_event()
