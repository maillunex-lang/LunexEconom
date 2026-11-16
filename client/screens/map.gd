extends Control
signal back_requested
signal wallet_changed
signal build_requested(parcel: Dictionary, cell: Vector2i)
signal enterprise_requested(id: int)
const API = preload("res://world/api.gd")
const Stream = preload("res://world/stream.gd")
const Canvas = preload("res://world/map_canvas.gd")
const Words = preload("res://world/strings.gd")
const Forest = preload("res://theme/forest_glass.gd")
const Gen = preload("res://world/generator.gd")
const Format = preload("res://i18n/format.gd")
const Components = preload("res://ui/components.gd")
var api: Node
var stream: Node
var canvas: Control
var options: OptionButton
var info: Label
var panel: PanelContainer
var parcel_title: Label
var parcel_zone: Label
var parcel_owner: Label
var parcel_price: Label
var parcel_road: Label
var road_button: Button
var road_finish: Button
var road_cancel: Button
var road_hint: Label
var road_selection: Array[Vector2i] = []
var _road_mode := false
var _road_busy := false
var buy_button: Button
var build_button: Button
var confirm: ConfirmationDialog
var selected := Vector2i(2147483647,2147483647)
var home_city := "ufa"
var _started := false
var _panel_visible := false
var _city_data: Dictionary = {}
var _enterprise_refresh_busy := false
var _map_area: Control
var _map_hint: Label
var _zoom_tools: VBoxContainer

func _ready() -> void:
    set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    api = API.new()
    api.name = "WorldApi"
    add_child(api)
    stream = Stream.new()
    stream.name = "WorldStream"
    add_child(stream)
    stream.configure(api)
    stream.network_error.connect(_on_error)
    stream.city_grew.connect(_on_growth)
    stream.enterprise_changed.connect(_refresh_enterprise_map)
    stream.cities_ready.connect(_refresh_city_options)
    stream.road_built.connect(func(_result: Dictionary):
        info.text = Words.get_text("world.road.done")
        _show_selected())
    stream.land_purchased.connect(func(_data: Dictionary):
        info.text = Words.get_text("world.parcel.bought")
        wallet_changed.emit()
        _show_selected())
    stream.parcels_ready.connect(func(_key: Vector2i,_items: Array):
        if _panel_visible: _show_selected())
    var root_layout := VBoxContainer.new()
    root_layout.name = "MapLayout"
    root_layout.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    add_child(root_layout)
    var header := HBoxContainer.new()
    header.name = "MapHeader"
    root_layout.add_child(header)
    var back := Button.new()
    back.text = Words.get_text("button.back")
    back.pressed.connect(func(): back_requested.emit())
    header.add_child(back)
    var title := Label.new()
    title.name = "MapTitle"
    title.text = Words.get_text("world.map.title")
    title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    header.add_child(title)
    options = OptionButton.new()
    options.name = "CityPicker"
    options.custom_minimum_size.x = 230.0
    options.tooltip_text = Words.get_text("world.map.choose")
    options.item_selected.connect(_choose_city)
    header.add_child(options)
    var home := Button.new()
    home.text = Words.get_text("world.map.home")
    home.pressed.connect(center_home)
    header.add_child(home)
    var area := Control.new()
    area.name = "MapArea"
    _map_area = area
    area.size_flags_vertical = Control.SIZE_EXPAND_FILL
    root_layout.add_child(area)
    canvas = Canvas.new()
    canvas.name = "WorldCanvas"
    canvas.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    area.add_child(canvas)
    canvas.attach(stream)
    canvas.parcel_tapped.connect(_on_parcel_tapped)
    canvas.cell_tapped.connect(_on_road_cell)
    panel = PanelContainer.new()
    panel.name = "ParcelPanel"
    panel.anchor_left = 1.0
    panel.anchor_right = 1.0
    panel.anchor_top = 0.0
    panel.anchor_bottom = 0.0
    panel.offset_left = -398.0
    panel.offset_right = -10.0
    panel.offset_top = 12.0
    panel.offset_bottom = 380.0
    panel.visible = false
    area.add_child(panel)
    panel.add_theme_stylebox_override("panel", Forest.rounded(Forest.COLORS.panel,18))
    var details := VBoxContainer.new()
    panel.add_child(details)
    parcel_title = Label.new()
    details.add_child(parcel_title)
    parcel_zone = Label.new()
    details.add_child(parcel_zone)
    parcel_owner = Label.new()
    details.add_child(parcel_owner)
    parcel_price = Label.new()
    details.add_child(parcel_price)
    parcel_road = Label.new()
    details.add_child(parcel_road)
    var actions := HBoxContainer.new()
    details.add_child(actions)
    buy_button = Button.new()
    buy_button.text = Words.get_text("world.parcel.buy")
    buy_button.pressed.connect(_confirm_purchase)
    actions.add_child(buy_button)
    build_button = Button.new()
    build_button.text = Words.get_text("world.parcel.build")
    build_button.disabled = true
    build_button.pressed.connect(_build_selected)
    actions.add_child(build_button)
    var road_actions := HBoxContainer.new()
    details.add_child(road_actions)
    road_button = Button.new()
    road_button.name = "RoadStart"
    road_button.text = Words.get_text("world.road.start")
    road_button.pressed.connect(_begin_road)
    road_actions.add_child(road_button)
    road_finish = Button.new()
    road_finish.name = "RoadFinish"
    road_finish.text = Words.get_text("world.road.finish")
    road_finish.pressed.connect(_finish_road)
    road_finish.visible = false
    road_actions.add_child(road_finish)
    road_cancel = Button.new()
    road_cancel.name = "RoadCancel"
    road_cancel.text = Words.get_text("world.road.cancel")
    road_cancel.pressed.connect(_cancel_road)
    road_cancel.visible = false
    road_actions.add_child(road_cancel)
    road_hint = Label.new()
    road_hint.name = "RoadHint"
    road_hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    details.add_child(road_hint)
    var close := Button.new()
    close.text = Words.get_text("button.close")
    close.pressed.connect(func(): panel.hide(); _panel_visible = false)
    actions.add_child(close)
    _zoom_tools = VBoxContainer.new()
    _zoom_tools.name = "ZoomTools"
    _zoom_tools.mouse_filter = Control.MOUSE_FILTER_PASS
    area.add_child(_zoom_tools)
    for item in [["ui2.map.zoom.in",1.2],["ui2.map.zoom.out",0.8333333]]:
        var zoom_button := Components.button(str(item[0]),"secondary")
        zoom_button.custom_minimum_size = Vector2(62,54)
        zoom_button.pressed.connect(_zoom_button.bind(float(item[1])))
        _zoom_tools.add_child(zoom_button)
    _map_hint = Label.new()
    _map_hint.name = "MapEmptyHint"
    _map_hint.text = Words.get_text("world.map.hint")
    _map_hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    _map_hint.mouse_filter = Control.MOUSE_FILTER_IGNORE
    _map_hint.add_theme_stylebox_override("normal", Forest.rounded(Forest.COLORS.panel,12))
    area.add_child(_map_hint)
    var legend := HBoxContainer.new()
    legend.name = "ZoneLegend"
    root_layout.add_child(legend)
    var legend_title := Label.new()
    legend_title.text = Words.get_text("world.map.legend")
    legend.add_child(legend_title)
    for zone_id in ["center","residential","industrial","free"]:
        var swatch := ColorRect.new()
        swatch.color = Canvas.TILE_COLORS[zone_id]
        swatch.custom_minimum_size = Vector2(16,16)
        swatch.mouse_filter = Control.MOUSE_FILTER_IGNORE
        legend.add_child(swatch)
        var name := Label.new()
        name.text = Words.get_text("world.zone."+zone_id)
        legend.add_child(name)
    var footer := HBoxContainer.new()
    root_layout.add_child(footer)
    info = Label.new()
    info.text = Words.get_text("world.map.ready")
    info.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    footer.add_child(info)
    var hint := Label.new()
    hint.text = Words.get_text("world.map.hint")
    footer.add_child(hint)
    confirm = ConfirmationDialog.new()
    confirm.title = Words.get_text("world.parcel.buy")
    confirm.ok_button_text = Words.get_text("world.parcel.buy")
    confirm.cancel_button_text = Words.get_text("button.cancel")
    confirm.confirmed.connect(_purchase)
    add_child(confirm)
    visibility_changed.connect(_visibility)
    resize_ui(get_viewport_rect().size)

func resize_ui(view_size: Vector2) -> void:
    Forest.apply_touch(self,view_size)
    if panel != null and _map_area != null:
        var area_width: float = _map_area.size.x if _map_area.size.x > 0 else view_size.x
        var area_height: float = _map_area.size.y if _map_area.size.y > 0 else view_size.y - 190.0
        var width: float = minf(390.0,maxf(280.0,area_width * 0.42))
        panel.offset_left = -width - 12.0
        panel.offset_right = -12.0
        panel.offset_top = 12.0
        panel.offset_bottom = minf(390.0,maxf(220.0,area_height - 18.0))
        if _zoom_tools != null:
            _zoom_tools.position = Vector2(12.0,16.0)
        if _map_hint != null:
            _map_hint.position = Vector2(88.0,20.0)
            _map_hint.custom_minimum_size.x = 0
            _map_hint.size = Vector2(maxf(100.0,area_width - width - 130.0),60.0)

func _zoom_button(multiplier: float) -> void:
    if canvas != null:
        canvas._zoom_at(canvas.zoom * multiplier,canvas.size * 0.5)

func open(url: String, access_token: String, preferred_city: String = "ufa") -> void:
    api.base_url = url
    api.token = access_token
    stream.set_server(url)
    canvas._last_view = Vector2i(999999,999999)
    if not preferred_city.is_empty():
        home_city = preferred_city
    stream.start()
    _refresh_enterprise_map()
    if not _started:
        _started = true
        _load_world()
    else:
        _focus_on_city(home_city)
        stream.poll_events()

func _visibility() -> void:
    if not visible and stream != null:
        stream.stop()

func _load_world() -> void:
    info.text = Words.get_text("world.map.ready")
    var ok: bool = await stream.load_cities()
    if not ok:
        info.text = Words.get_text("world.map.offline")
        _started = false
        return
    _refresh_city_options()
    _focus_on_city(home_city)
    info.text = Words.get_text("world.map.online")
    stream.poll_events()

func _refresh_city_options() -> void:
    options.clear()
    _city_data.clear()
    for city in stream.cities:
        var city_id: String = str(city.get("id", ""))
        _city_data[city_id] = city
        options.add_item(str(city.get("name", city_id)))
        options.set_item_metadata(options.item_count - 1, city_id)

func _choose_city(index: int) -> void:
    _focus_on_city(str(options.get_item_metadata(index)))

func _focus_on_city(id: String) -> void:
    if not _city_data.has(id):
        return
    var city: Dictionary = _city_data[id]
    stream.set_city(id)
    canvas._last_view = Vector2i(999999,999999)
    var at: Dictionary = city.get("center", {})
    canvas.focus(Vector2i(int(at.get("x", city.get("x", 0))),int(at.get("y", city.get("y", 0)))))
    for i in range(options.item_count):
        if options.get_item_metadata(i) == id:
            options.select(i)
            break
    panel.hide()
    _panel_visible = false
    _cancel_road()
    canvas.preview = {}
    canvas.queue_redraw()

func center_home() -> void:
    _focus_on_city(home_city)

func _on_error(code: String) -> void:
    info.text = Words.get_text("world.error." + code if code in ["network", "timeout", "unauthorized"] else "world.error.other")

func _on_growth(_event: Dictionary) -> void:
    info.text = Words.get_text("world.map.growth")

func _on_parcel_tapped(px: int, py: int) -> void:
    for chunk in canvas.building_cells:
        for cell in canvas.building_cells[chunk]:
            if Gen.floor_div(int(cell["x"]),6) == px and Gen.floor_div(int(cell["y"]),6) == py:
                var reference := str(cell.get("ref",""))
                if reference.begins_with("enterprise:") and reference.get_slice(":",1).is_valid_int():
                    enterprise_requested.emit(int(reference.get_slice(":",1)))
                    return
    _cancel_road()
    selected = Vector2i(px, py)
    _panel_visible = true
    panel.show()
    if _map_hint != null: _map_hint.hide()
    _show_selected()

func _show_selected() -> void:
    if not _panel_visible:
        return
    parcel_title.text = Words.get_text("world.parcel.title",{"px":selected.x,"py":selected.y})
    var parcel: Dictionary = stream.parcel_at(selected.x,selected.y)
    if parcel.is_empty():
        parcel_zone.text = Words.get_text("world.parcel.loading")
        parcel_owner.text = ""
        parcel_price.text = ""
        parcel_road.text = ""
        road_button.disabled = true
        buy_button.disabled = true
        build_button.disabled = true
        _fetch_parcel(selected)
        return
    var representative: Dictionary = stream.cell_at(selected.x*6+3,selected.y*6+3)
    var zone_id: String = str(representative.get("zone",parcel.get("zone","free")))
    parcel_zone.text = Words.get_text("world.parcel.zone",{"zone":Words.get_text("world.zone."+zone_id)})
    var owner_id: String = str(parcel.get("owner_kind","state"))
    var owner_text := Words.get_text("world.parcel."+owner_id) if owner_id in ["city","state","player","company"] else str(parcel.get("owner_ref",""))
    parcel_owner.text = Words.get_text("world.parcel.owner",{"owner":owner_text})
    parcel_price.text = Words.get_text("world.parcel.price",{"price":Format.number(parcel["price"])}) if parcel.has("price") else Words.get_text("world.parcel.price_not_available")
    parcel_road.text = Words.get_text("world.parcel.road.yes" if stream.road_near_parcel(selected.x,selected.y) else "world.parcel.road.no")
    road_button.disabled = owner_id != "player" or _road_busy
    road_button.visible = not _road_mode
    buy_button.disabled = not owner_id in ["city","state"] or not parcel.has("price")
    build_button.disabled = owner_id != "player"

func _fetch_parcel(target: Vector2i) -> void:
    var key := Vector2i(Gen.floor_div(target.x,2),Gen.floor_div(target.y,2))
    var response: Dictionary = await api.fetch("/land/parcels?chunk=%d,%d" % [key.x,key.y])
    if response.get("code",0)==200:
        stream.parcels[key] = response.get("data",{}).get("parcels",[])
        if stream.cache.has(key):
            stream.cache[key]["parcels"] = stream.parcels[key]
            stream.device_cache.save_chunk(stream.city_id,key,stream.cache[key])
        if target == selected and _panel_visible:
            _show_selected()
    else:
        parcel_zone.text = Words.get_text("world.parcel.unavailable")

func _confirm_purchase() -> void:
    var parcel: Dictionary = stream.parcel_at(selected.x,selected.y)
    if not parcel.get("owner_kind","") in ["city","state"] or not parcel.has("price"):
        return
    confirm.dialog_text = Words.get_text("world.parcel.confirm",{"price":Format.number(parcel["price"])})
    confirm.popup_centered()

func _purchase() -> void:
    var target := selected
    buy_button.disabled = true
    info.text = Words.get_text("world.parcel.working")
    var result: Dictionary = await stream.buy(target.x,target.y)
    if result.get("code",0) not in [200,201]:
        var error_id: String = str(result.get("data",{}).get("error","other"))
        info.text = Words.get_text("error.build."+error_id) if error_id in ["payment_failed","parcel_unavailable","request_id_conflict","unauthorized"] else Words.get_text("world.parcel.failed")
        if target == selected:
            buy_button.disabled = false

func _build_selected() -> void:
    var parcel: Dictionary = stream.parcel_at(selected.x, selected.y)
    if str(parcel.get("owner_kind", "")) != "player":
        return
    var cell := Vector2i(selected.x*6, selected.y*6)
    var chunk := Vector2i(Gen.floor_div(cell.x,12), Gen.floor_div(cell.y,12))
    var snapshot: Dictionary = stream.chunks.get(chunk, {})
    var zones: Array = snapshot.get("zones", [])
    if zones.size() > posmod(cell.y,12) and zones[posmod(cell.y,12)].size() > posmod(cell.x,12):
        parcel["zone"] = str(zones[posmod(cell.y,12)][posmod(cell.x,12)])
    parcel["road_near"] = stream.road_near_parcel(selected.x,selected.y)
    var site_cells: Array = []
    for cy in range(selected.y*6-1,selected.y*6+7):
        for cx in range(selected.x*6-1,selected.x*6+7):
            var status: Dictionary = stream.cell_at(cx,cy)
            if not status.is_empty():
                status["x"] = cx
                status["y"] = cy
                site_cells.append(status)
    parcel["site_cells"] = site_cells
    parcel["px"] = selected.x
    parcel["py"] = selected.y
    build_requested.emit(parcel, cell)

func _refresh_enterprise_map() -> void:
    if _enterprise_refresh_busy:
        return
    _enterprise_refresh_busy = true
    var response: Dictionary = await api.fetch("/enterprises")
    if int(response.get("code",0)) == 200:
        var metadata := {}
        for id in response.get("data",{}).get("enterprises",[]):
            var detail: Dictionary = await api.fetch("/enterprises/%d" % int(id))
            if int(detail.get("code",0)) == 200:
                metadata["enterprise:%d" % int(id)] = detail.get("data",{})
        canvas.enterprise_info = metadata
        canvas.refresh_buildings()
    _enterprise_refresh_busy = false

func _begin_road() -> void:
    if str(stream.parcel_at(selected.x,selected.y).get("owner_kind","")) != "player":
        info.text = Words.get_text("world.road.no_owned")
        return
    _road_mode = true
    road_selection.clear()
    canvas.road_mode = true
    canvas.road_preview.clear()
    canvas.queue_redraw()
    road_button.visible = false
    road_finish.visible = true
    road_cancel.visible = true
    road_finish.disabled = true
    road_hint.text = Words.get_text("world.road.instructions")
    info.text = Words.get_text("world.road.instructions")

func _cancel_road() -> void:
    _road_mode = false
    road_selection.clear()
    if canvas != null:
        canvas.road_mode = false
        canvas.road_preview.clear()
        canvas.queue_redraw()
    if road_button != null:
        road_button.visible = true
    if road_finish != null:
        road_finish.visible = false
    if road_cancel != null:
        road_cancel.visible = false
    if road_hint != null:
        road_hint.text = ""

func _on_road_cell(cell: Vector2i) -> void:
    if not _road_mode or _road_busy:
        return
    if cell.x<selected.x*6 or cell.x>=selected.x*6+6 or cell.y<selected.y*6 or cell.y>=selected.y*6+6:
        info.text = Words.get_text("world.road.no_owned")
        return
    var status: Dictionary = stream.cell_at(cell.x,cell.y)
    if status.is_empty() or str(status.get("terrain",""))=="water" or bool(status.get("road",false)) or bool(status.get("occupied",false)) or road_selection.has(cell):
        info.text = Words.get_text("world.road.invalid_cell")
        return
    var connected := false
    var neighbors := [Vector2i(cell.x-1,cell.y),Vector2i(cell.x+1,cell.y),
        Vector2i(cell.x,cell.y-1),Vector2i(cell.x,cell.y+1)]
    for next_cell in neighbors:
        if road_selection.is_empty() and bool(stream.cell_at(next_cell.x,next_cell.y).get("road",false)):
            connected = true
        elif not road_selection.is_empty() and road_selection.has(next_cell):
            connected = true
    if not connected:
        info.text = Words.get_text("world.road.not_connected")
        return
    road_selection.append(cell)
    canvas.road_preview = road_selection.duplicate()
    canvas.queue_redraw()
    road_finish.disabled = road_selection.is_empty()
    info.text = Words.get_text("world.road.preview",{"count":road_selection.size()})

func _finish_road() -> void:
    if _road_busy:
        return
    if road_selection.is_empty():
        info.text = Words.get_text("world.road.minimum")
        return
    _road_busy = true
    road_finish.disabled = true
    info.text = Words.get_text("world.road.working")
    var answer: Dictionary = await stream.build_road(road_selection)
    _road_busy = false
    if int(answer.get("code",0)) == 200:
        _cancel_road()
        _show_selected()
        info.text = Words.get_text("world.road.done")
    else:
        var error_code := str(answer.get("data",{}).get("error","unknown"))
        if error_code in ["invalid_road_cells","duplicate_road_cells","roads_must_form_one_connected_path",
                "road_crosses_city_boundary","parcel_not_owned","water_requires_bridge",
                "road_overlaps_building","no_road_connection","unauthorized"]:
            info.text = Words.get_text("error.build."+error_code)
        else:
            info.text = Words.get_text("error.build.unknown") + " " + Words.get_text("error.build.code",{"code":error_code})
        road_finish.disabled = false
