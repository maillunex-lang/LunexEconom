extends Control
@onready var world = $World
@onready var hud: MarginContainer = $HUD
@onready var info: Label = $HUD/Top/Info
func _ready() -> void:
    add_to_group("world_hud")
    get_viewport().size_changed.connect(_update_safe_area)
    call_deferred("_update_safe_area")
    $HUD/Top/Expand.pressed.connect(_expand)
    $HUD/Top/Connect.pressed.connect(_connect)
    _setup_build_toolbar()
    _setup_ui_v1()
    _connect_server()
    var sync = load("res://world_sync.gd").new()
    sync.world = world
    add_child(sync)
    var updater = load("res://updater.gd").new()
    updater.name = "Updater"
    add_child(updater)
    updater.state_changed.connect(_on_update_state)
    $HUD/Top/Update.pressed.connect(func() -> void:
        if not updater.downloaded_apk.is_empty():
            updater.install_apk()
        elif not updater.manifest.is_empty() and int(updater.manifest["apk"]["version_code"]) > 11:
            updater.download_apk()
        else:
            updater.check()
    )
    updater.check()
func set_selection(cell: Vector2i) -> void:
    info.text = "Регион 01 · Участок %d:%d" % [cell.x, cell.y]
    if world.build_type.is_empty() and details_panel != null:
        var kind: String = world.building_at(cell)
        if kind.is_empty():
            details_panel.hide()
        else:
            details_panel.get_node("VBoxContainer/Title").text = "Предприятие: " + kind
            details_panel.show()
func _update_safe_area() -> void:
    var v := get_viewport_rect().size
    var s := DisplayServer.screen_get_size()
    var safe := DisplayServer.get_display_safe_area()
    var left := 20
    var top := 20
    var right := 20
    var bottom := 20
    if OS.has_feature("mobile") and s.x > 0 and s.y > 0 and safe.size.x > 0:
        left = maxi(left, int(float(safe.position.x) * v.x / s.x) + 12)
        top = maxi(top, int(float(safe.position.y) * v.y / s.y) + 12)
        right = maxi(right, int(float(s.x - safe.end.x) * v.x / s.x) + 12)
        bottom = maxi(bottom, int(float(s.y - safe.end.y) * v.y / s.y) + 12)
    hud.add_theme_constant_override("margin_left", left)
    hud.add_theme_constant_override("margin_top", top)
    hud.add_theme_constant_override("margin_right", right)
    hud.add_theme_constant_override("margin_bottom", bottom)
    if build_toolbar != null:
        build_toolbar.offset_bottom = -float(bottom)
        build_toolbar.offset_top = -float(bottom) - 72.0

func _expand() -> void:
    world.expand_city(2)
    info.text = "Территория: ±%d клеток" % world.expansion_radius

func _connect() -> void:
    if world.selected == Vector2i(-1, -1):
        info.text = "Выберите клетку для дороги"
        return
    if world.commit_access_road(world.selected):
        var path: Array[Vector2i] = world.roads.route(world.selected, Vector2i(0, 0))
        info.text = "Дорога подключена · маршрут %d клеток" % path.size()
    else:
        info.text = "Подключение невозможно"

func _connect_server() -> void:
    var req := HTTPRequest.new()
    add_child(req)
    req.timeout = 8.0
    req.request_completed.connect(func(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
        if result == HTTPRequest.RESULT_SUCCESS and code == 200:
            var data = JSON.parse_string(body.get_string_from_utf8())
            info.text = "Сервер: подключён · Мир: %s" % str(data.get("world_id", "?")) if data is Dictionary else "Ошибка данных сервера"
        else:
            info.text = "Сервер недоступен · HTTP %d" % code
        req.queue_free()
    )
    var err := req.request("https://rikagro.ru/lunexeconom/api/world")
    if err != OK:
        info.text = "Ошибка соединения: %d" % err
        req.queue_free()

func _on_update_state(message: String, can_install: bool) -> void:
    $HUD/Top/Update.text = "Установить" if can_install else "Обновить"
    $HUD/Top/Update.tooltip_text = message
    $HUD/Top/UpdateStatus.text = message
var catalog_panel: PanelContainer
var placement_panel: PanelContainer
var details_panel: PanelContainer
var catalog_buttons: Array[Button] = []
var ui_pending := false
var build_toolbar: HBoxContainer
var build_hint: Label
var toolbar_touches: Dictionary = {}
var toolbar_mouse_button: Button = null

func _style() -> StyleBoxFlat:
    var st := StyleBoxFlat.new()
    st.bg_color = Color(0.08, 0.17, 0.15, 0.94)
    st.set_corner_radius_all(16)
    st.set_content_margin_all(12)
    return st

func _ui_button(label: String, callback: Callable, width: float = 130) -> Button:
    var b := Button.new()
    b.text = label
    b.custom_minimum_size = Vector2(width, 58)
    b.add_theme_font_size_override("font_size", 18)
    b.pressed.connect(callback)
    return b

func _setup_build_toolbar() -> void:
    build_toolbar = HBoxContainer.new()
    build_toolbar.name = "BottomNavigation"
    build_toolbar.alignment = BoxContainer.ALIGNMENT_CENTER
    build_toolbar.add_theme_constant_override("separation", 8)
    add_child(build_toolbar)
    build_toolbar.set_anchors_preset(Control.PRESET_BOTTOM_WIDE)
    build_toolbar.offset_top = -94
    build_toolbar.offset_bottom = -20
    build_toolbar.add_child(_ui_button("Строить", func(): catalog_panel.show(); placement_panel.hide(); details_panel.hide()))
    build_toolbar.add_child(_ui_button("Дороги", func(): info.text = "Выберите участок для дороги"))
    build_toolbar.add_child(_ui_button("Экономика", func(): info.text = "Экономика: в разработке"))
    build_toolbar.add_child(_ui_button("Логистика", func(): info.text = "Логистика: в разработке"))
    build_toolbar.add_child(_ui_button("Меню", func(): info.text = "Меню: в разработке"))

func _setup_ui_v1() -> void:
    catalog_panel = PanelContainer.new()
    catalog_panel.name = "BuildCatalog"
    catalog_panel.add_theme_stylebox_override("panel", _style())
    add_child(catalog_panel)
    var content := VBoxContainer.new()
    catalog_panel.add_child(content)
    content.add_child(_ui_button("Строительство  ×", func(): catalog_panel.hide(), 230))
    var tiles := HBoxContainer.new()
    content.add_child(tiles)
    for entry in [["farm","Ферма 2×2"],["mine","Шахта 2×3"],["factory","Завод 3×2"]]:
        var kind: String = entry[0]
        tiles.add_child(_ui_button(entry[1], func(): _choose_ui_build(kind), 170))
    catalog_panel.hide()
    placement_panel = PanelContainer.new()
    placement_panel.name = "PlacementCard"
    placement_panel.add_theme_stylebox_override("panel", _style())
    add_child(placement_panel)
    var place_content := VBoxContainer.new()
    placement_panel.add_child(place_content)
    build_hint = Label.new()
    build_hint.text = "Выберите участок на карте"
    build_hint.add_theme_font_size_override("font_size", 19)
    place_content.add_child(build_hint)
    var actions := HBoxContainer.new()
    place_content.add_child(actions)
    actions.add_child(_ui_button("Построить", _place_building, 210))
    actions.add_child(_ui_button("Отмена", _cancel_ui_build, 170))
    placement_panel.hide()
    details_panel = PanelContainer.new()
    details_panel.name = "EnterpriseDetails"
    details_panel.add_theme_stylebox_override("panel", _style())
    add_child(details_panel)
    var details_content := VBoxContainer.new()
    details_panel.add_child(details_content)
    var title := Label.new()
    title.name = "Title"
    details_content.add_child(title)
    details_content.add_child(_ui_button("Закрыть", func(): details_panel.hide()))
    details_panel.hide()
    get_viewport().size_changed.connect(_layout_ui_v1)
    call_deferred("_layout_ui_v1")

func _layout_ui_v1() -> void:
    var size := get_viewport_rect().size
    catalog_panel.position = Vector2(maxf(20, (size.x - catalog_panel.size.x) * 0.5), size.y - catalog_panel.size.y - 125)
    placement_panel.position = Vector2(maxf(20, (size.x - placement_panel.size.x) * 0.5), size.y - placement_panel.size.y - 125)
    details_panel.position = Vector2(size.x - details_panel.size.x - 22, maxf(85, (size.y - details_panel.size.y) * 0.5))

func _choose_ui_build(kind: String) -> void:
    world.choose_build(kind)
    catalog_panel.hide()
    placement_panel.show()
    details_panel.hide()
    build_hint.text = "Выберите участок на карте"

func _cancel_ui_build() -> void:
    world.cancel_build()
    placement_panel.hide()
    info.text = "Строительство отменено"

func show_build_preview(result: Dictionary) -> void:
    if result.get("ok", false):
        info.text = "Участок подходит · нажмите Построить"
        if build_hint != null: build_hint.text = info.text
    else:
        var messages := {
            "road_overlap": "Нельзя строить на дороге",
            "occupied": "Участок занят",
            "no_road_access": "Нужен подъезд к дороге",
            "outside_explored_area": "Территория ещё не открыта",
            "invalid_size": "Неверный размер участка"
        }
        info.text = str(messages.get(str(result.get("reason", "")), "Участок не подходит"))
        if build_hint != null: build_hint.text = info.text

func _place_building() -> void:
    if ui_pending: return
    ui_pending = true
    var result: Dictionary = world.place_building()
    if result.get("ok", false):
        world.cancel_build()
        placement_panel.hide()
        info.text = "Здание размещено (локальный прототип)"
    else:
        show_build_preview(result)
    ui_pending = false

func is_world_ui_point(point: Vector2) -> bool:
    if $HUD/Top.get_global_rect().has_point(point): return true
    for panel in [build_toolbar, catalog_panel, placement_panel, details_panel]:
        if panel != null and panel.visible and panel.get_global_rect().has_point(point):
            return true
    return false