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
var buy_button: Button
var build_button: Button
var confirm: ConfirmationDialog
var selected := Vector2i(2147483647,2147483647)
var home_city := "ufa"
var _started := false
var _panel_visible := false
var _city_data: Dictionary = {}
var _enterprise_refresh_busy := false

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
    area.size_flags_vertical = Control.SIZE_EXPAND_FILL
    root_layout.add_child(area)
    canvas = Canvas.new()
    canvas.name = "WorldCanvas"
    canvas.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    area.add_child(canvas)
    canvas.attach(stream)
    canvas.parcel_tapped.connect(_on_parcel_tapped)
    panel = PanelContainer.new()
    panel.name = "ParcelPanel"
    panel.anchor_left = 1.0
    panel.anchor_right = 1.0
    panel.anchor_top = 0.0
    panel.anchor_bottom = 0.0
    panel.offset_left = -398.0
    panel.offset_right = -10.0
    panel.offset_top = 12.0
    panel.offset_bottom = 288.0
    panel.visible = false
    area.add_child(panel)
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
    var actions := HBoxContainer.new()
    details.add_child(actions)
    buy_button = Button.new()
    buy_button.text = Words.get_text("world.parcel.buy")
    buy_button.pressed.connect(_confirm_purchase)
    actions.add_child(buy_button)
    build_button = Button.new()
    build_button.text = "Построить"
    build_button.disabled = true
    build_button.pressed.connect(_build_selected)
    actions.add_child(build_button)
    var close := Button.new()
    close.text = Words.get_text("button.close")
    close.pressed.connect(func(): panel.hide(); _panel_visible = false)
    actions.add_child(close)
    var footer := HBoxContainer.new()
    root_layout.add_child(footer)
    info = Label.new()
    info.text = Words.get_text("world.map.loading")
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
    if panel != null:
        panel.offset_left = -minf(398.0, view_size.x * 0.46)
        panel.offset_bottom = minf(290.0,view_size.y*0.52)

func open(url: String, access_token: String, preferred_city: String = "ufa") -> void:
    api.base_url = url
    api.token = access_token
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
    info.text = Words.get_text("world.map.loading")
    var ok: bool = await stream.load_cities()
    if not ok:
        info.text = Words.get_text("world.map.offline")
        _started = false
        return
    options.clear()
    _city_data.clear()
    for city in stream.cities:
        var city_id: String = str(city.get("id", ""))
        _city_data[city_id] = city
        options.add_item(str(city.get("name", city_id)))
        options.set_item_metadata(options.item_count - 1, city_id)
    _focus_on_city(home_city)
    info.text = Words.get_text("world.map.online")
    stream.poll_events()

func _choose_city(index: int) -> void:
    _focus_on_city(str(options.get_item_metadata(index)))

func _focus_on_city(id: String) -> void:
    if not _city_data.has(id):
        return
    var city: Dictionary = _city_data[id]
    var at: Dictionary = city.get("center", {})
    canvas.focus(Vector2i(int(at.get("x", city.get("x", 0))),int(at.get("y", city.get("y", 0)))))
    for i in range(options.item_count):
        if options.get_item_metadata(i) == id:
            options.select(i)
            break
    panel.hide()
    _panel_visible = false
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
    selected = Vector2i(px, py)
    _panel_visible = true
    panel.show()
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
        buy_button.disabled = true
        build_button.disabled = true
        _fetch_parcel(selected)
        return
    var zone_id: String = str(parcel.get("zone", "free"))
    parcel_zone.text = Words.get_text("world.parcel.zone",{"zone":Words.get_text("world.zone."+zone_id)})
    var owner_id: String = str(parcel.get("owner_kind","state"))
    var owner_text := Words.get_text("world.parcel."+owner_id) if owner_id in ["city","state","player","company"] else str(parcel.get("owner_ref",""))
    parcel_owner.text = Words.get_text("world.parcel.owner",{"owner":owner_text})
    parcel_price.text = Words.get_text("world.parcel.price",{"price":str(parcel.get("price","—"))})
    buy_button.disabled = not owner_id in ["city","state"] or not parcel.has("price")
    build_button.disabled = owner_id != "player"

func _fetch_parcel(target: Vector2i) -> void:
    var key := Vector2i(Gen.floor_div(target.x,2),Gen.floor_div(target.y,2))
    var response: Dictionary = await api.fetch("/land/parcels?chunk=%d,%d" % [key.x,key.y])
    if response.get("code",0)==200:
        stream.parcels[key] = response.get("data",{}).get("parcels",[])
        if target == selected and _panel_visible:
            _show_selected()
    else:
        parcel_zone.text = Words.get_text("world.parcel.unavailable")

func _confirm_purchase() -> void:
    var parcel: Dictionary = stream.parcel_at(selected.x,selected.y)
    if not parcel.get("owner_kind","") in ["city","state"] or not parcel.has("price"):
        return
    confirm.dialog_text = Words.get_text("world.parcel.confirm",{"price":parcel["price"]})
    confirm.popup_centered()

func _purchase() -> void:
    var target := selected
    buy_button.disabled = true
    info.text = Words.get_text("world.parcel.working")
    var result: Dictionary = await stream.buy(target.x,target.y)
    if result.get("code",0) not in [200,201]:
        var error_id: String = str(result.get("data",{}).get("error","other"))
        info.text = Words.get_text("world.error."+error_id if error_id in ["payment_failed","parcel_unavailable","request_id_conflict","unauthorized"] else "world.parcel.failed")
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
        canvas.queue_redraw()
    _enterprise_refresh_busy = false