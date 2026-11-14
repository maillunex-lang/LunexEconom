extends Control
@onready var world = $World
@onready var hud: MarginContainer = $HUD
@onready var info: Label = $HUD/Top/Info
func _ready() -> void:
    var overlay := CanvasLayer.new()
    overlay.name = "UIOverlay"
    overlay.layer = 10
    add_child(overlay)
    # Plain remove/add instead of reparent(): reparent keeps the global
    # transform and rewrites the Control offsets, which broke HUD layout.
    remove_child(hud)
    overlay.add_child(hud)
    hud.set_anchors_and_offsets_preset(Control.PRESET_TOP_WIDE)
    add_to_group("world_hud")
    get_viewport().size_changed.connect(_update_safe_area)
    call_deferred("_update_safe_area")
    $UIOverlay/HUD/Top/Expand.pressed.connect(_expand)
    $UIOverlay/HUD/Top/Connect.pressed.connect(_connect)
    _setup_build_toolbar()
    _setup_ui_v1()
    _setup_top_hud()
    _connect_server()
    var sync = load("res://world_sync.gd").new()
    sync.world = world
    add_child(sync)
    var updater = load("res://updater.gd").new()
    updater.name = "Updater"
    add_child(updater)
    updater.state_changed.connect(_on_update_state)
    $UIOverlay/HUD/Top/Update.pressed.connect(func() -> void:
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
            _show_panel(details_panel)
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
        build_toolbar.offset_top = -float(bottom) - 68.0
    if catalog_panel != null: _layout_ui_v1()

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
    $UIOverlay/HUD/Top/Update.text = "Установить" if can_install else "Обновить"
    $UIOverlay/HUD/Top/Update.tooltip_text = message
    $UIOverlay/HUD/Top/UpdateStatus.text = message
var section_panel: PanelContainer
var section_title: Label
var section_body: Label
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
    st.border_color = Color("#315647")
    st.set_border_width_all(1)
    return st

func _ui_button(label: String, callback: Callable, width: float = 130) -> Button:
    var b := Button.new()
    b.text = label
    b.mouse_filter = Control.MOUSE_FILTER_IGNORE
    b.custom_minimum_size = Vector2(width, 58)
    b.add_theme_font_size_override("font_size", 16)
    var normal := StyleBoxFlat.new()
    normal.bg_color = Color("#315647")
    normal.set_corner_radius_all(12)
    normal.set_content_margin_all(7)
    b.add_theme_stylebox_override("normal", normal)
    var hover := normal.duplicate()
    hover.bg_color = Color("#48725d")
    b.add_theme_stylebox_override("hover", hover)
    var pressed := normal.duplicate()
    pressed.bg_color = Color("#e7b45d")
    b.add_theme_stylebox_override("pressed", pressed)
    b.add_theme_color_override("font_color", Color("#e8efe9"))
    b.pressed.connect(callback)
    return b

func _setup_build_toolbar() -> void:
    build_toolbar = HBoxContainer.new()
    build_toolbar.name = "BottomNavigation"
    build_toolbar.alignment = BoxContainer.ALIGNMENT_CENTER
    build_toolbar.add_theme_constant_override("separation", 8)
    get_node("UIOverlay").add_child(build_toolbar)
    build_toolbar.set_anchors_preset(Control.PRESET_BOTTOM_WIDE)
    build_toolbar.offset_top = -94
    build_toolbar.offset_bottom = -20
    build_toolbar.add_child(_ui_button("Строить", _open_catalog))
    build_toolbar.add_child(_ui_button("Дороги", func(): _open_section("Дороги")))
    build_toolbar.add_child(_ui_button("Экономика", func(): _open_section("Экономика")))
    build_toolbar.add_child(_ui_button("Логистика", func(): _open_section("Логистика")))
    build_toolbar.add_child(_ui_button("Меню", func(): _open_section("Меню")))
    for child in build_toolbar.get_children():
        child.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    build_toolbar.add_theme_constant_override("separation", 6)

func _setup_ui_v1() -> void:
    catalog_panel = PanelContainer.new()
    catalog_panel.name = "BuildCatalog"
    catalog_panel.add_theme_stylebox_override("panel", _style())
    get_node("UIOverlay").add_child(catalog_panel)
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
    get_node("UIOverlay").add_child(placement_panel)
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
    get_node("UIOverlay").add_child(details_panel)
    var details_content := VBoxContainer.new()
    details_panel.add_child(details_content)
    var title := Label.new()
    title.name = "Title"
    details_content.add_child(title)
    details_content.add_child(_ui_button("Закрыть", func(): details_panel.hide()))
    details_panel.hide()
    section_panel = PanelContainer.new()
    section_panel.name = "SectionPanel"
    section_panel.add_theme_stylebox_override("panel", _style())
    get_node("UIOverlay").add_child(section_panel)
    var section_content := VBoxContainer.new()
    section_panel.add_child(section_content)
    var header := HBoxContainer.new()
    section_content.add_child(header)
    section_title = Label.new()
    section_title.add_theme_font_size_override("font_size", 23)
    section_title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    header.add_child(section_title)
    header.add_child(_ui_button("Закрыть ×", func(): section_panel.hide(), 120))
    section_body = Label.new()
    section_body.add_theme_font_size_override("font_size", 18)
    section_body.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    section_body.custom_minimum_size = Vector2(360, 105)
    section_content.add_child(section_body)
    section_panel.hide()
    get_viewport().size_changed.connect(_layout_ui_v1)
    call_deferred("_layout_ui_v1")

func _layout_ui_v1(override_size: Vector2 = Vector2.ZERO) -> void:
    var size := override_size if override_size != Vector2.ZERO else get_viewport_rect().size
    var usable_width := size.x - 40.0
    catalog_panel.size.x = minf(565.0, usable_width)
    placement_panel.size.x = minf(420.0, usable_width)
    details_panel.size.x = minf(275.0, usable_width * 0.46)
    var bottom_safe := 20.0
    var screen := DisplayServer.screen_get_size()
    var safe := DisplayServer.get_display_safe_area()
    if OS.has_feature("mobile") and screen.y > 0 and safe.size.y > 0:
        bottom_safe = maxf(20.0, (screen.y - safe.end.y) * size.y / screen.y + 12.0)
    build_toolbar.set_anchors_preset(Control.PRESET_TOP_LEFT)
    build_toolbar.position = Vector2(maxf(18, (size.x - minf(size.x - 36, 830)) * 0.5), size.y - bottom_safe - 70)
    build_toolbar.size = Vector2(minf(size.x - 36, 830), 62)
    var nav_top := build_toolbar.position.y
    catalog_panel.position = Vector2((size.x - catalog_panel.size.x) * 0.5, maxf(65, nav_top - catalog_panel.size.y - 12))
    placement_panel.position = Vector2((size.x - placement_panel.size.x) * 0.5, maxf(65, nav_top - placement_panel.size.y - 12))
    details_panel.position = Vector2(size.x - details_panel.size.x - 22, maxf(85, (size.y - details_panel.size.y) * 0.5))
    if section_panel != null:
        section_panel.size.x = minf(500, usable_width)
        section_panel.position = Vector2((size.x - section_panel.size.x) * 0.5, maxf(65, nav_top - section_panel.size.y - 12))

func _setup_top_hud() -> void:
    var top: HBoxContainer = $UIOverlay/HUD/Top
    info.text = "Башкортостан · Моя компания"
    info.add_theme_font_size_override("font_size", 16)
    $UIOverlay/HUD/Top/Expand.hide()
    $UIOverlay/HUD/Top/Connect.hide()
    $UIOverlay/HUD/Top/UpdateStatus.hide()
    $UIOverlay/HUD/Top/Update.text = "Обновление"
    $UIOverlay/HUD/Top/Update.custom_minimum_size = Vector2(118, 48)
    var money := Label.new()
    money.name = "Balance"
    money.text = "₽ —"
    money.tooltip_text = "Баланс появится после подключения экономики"
    money.add_theme_font_size_override("font_size", 18)
    top.add_child(money)
    top.move_child(money, 1)

func _show_panel(panel: Control) -> void:
    panel.show()
    panel.modulate.a = 0.0
    var tween := create_tween()
    tween.tween_property(panel, "modulate:a", 1.0, 0.2).set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_OUT)

func _open_section(section: String) -> void:
    world.cancel_build()
    catalog_panel.hide()
    placement_panel.hide()
    details_panel.hide()
    section_title.text = section
    match section:
        "Дороги":
            section_body.text = "Выберите клетку на карте и нажмите «Проложить дорогу». Подключение проверяется по дорожной сети."
        "Экономика":
            section_body.text = "Экономика предприятия пока не подключена. Баланс и производственные показатели появятся после реализации серверной экономики."
        "Логистика":
            section_body.text = "Маршруты поставок и транспортные задания находятся в разработке. Дорожная сеть доступна на карте."
        "Меню":
            section_body.text = "Башкирия: Мёд и Нефть\nВерсия интерфейса 1.0\nУправление: одним пальцем двигайте карту, двумя изменяйте масштаб."
    _show_panel(section_panel)
    call_deferred("_layout_ui_v1")

func _open_catalog() -> void:
    world.cancel_build()
    _show_panel(catalog_panel)
    placement_panel.hide()
    details_panel.hide()
    section_panel.hide()
    call_deferred("_layout_ui_v1")

func _choose_ui_build(kind: String) -> void:
    world.choose_build(kind)
    catalog_panel.hide()
    _show_panel(placement_panel)
    details_panel.hide()
    build_hint.text = "Выберите участок на карте"
    call_deferred("_layout_ui_v1")

func _cancel_ui_build() -> void:
    world.cancel_build()
    placement_panel.hide()
    info.text = "Строительство отменено"

func show_build_preview(result: Dictionary) -> void:
    if result.get("ok", false):
        var road_len: int = (result.get("access", []) as Array).size()
        info.text = "Участок подходит · нажмите Построить" if road_len == 0 else "Участок подходит · дорога %d кл. построится сама" % road_len
        if build_hint != null: build_hint.text = info.text
    else:
        var messages := {
            "road_overlap": "Нельзя строить на дороге",
            "occupied": "Участок занят",
            "no_road_access": "Нужен подъезд к дороге",
            "outside_explored_area": "Территория ещё не открыта",
            "invalid_size": "Неверный размер участка",
            "no_selection": "Сначала выберите участок",
            "server_occupied": "Участок занят серверным объектом",
            "water": "На воде строить нельзя"
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
        info.text = "Построено: %s · участок %s · дорога +%d" % [str(result.get("object_id", "")), str(world.selected), int(result.get("road_cells", 0))]
    else:
        show_build_preview(result)
    ui_pending = false

func is_world_ui_point(point: Vector2) -> bool:
    if $UIOverlay/HUD/Top.get_global_rect().has_point(point): return true
    for panel in [build_toolbar, catalog_panel, placement_panel, details_panel, section_panel]:
        if panel != null and panel.visible and panel.get_global_rect().has_point(point):
            return true
    return false

# Dedicated touch router for Android: GUI focus can be unavailable on
# canvas-stretched viewports. Only route releases inside the same button.
var ui_touch_buttons: Dictionary = {}
var ui_mouse_button: Button = null
func _hit_ui_button(point: Vector2) -> Button:
    for panel in [catalog_panel, placement_panel, details_panel, section_panel, build_toolbar]:
        if panel == null or not panel.visible or not panel.get_global_rect().has_point(point):
            continue
        var stack: Array[Node] = [panel]
        while not stack.is_empty():
            var node: Node = stack.pop_back()
            if node is Button and node.visible and node.get_global_rect().has_point(point):
                return node
            for child in node.get_children():
                stack.append(child)
    return null

func _input(event: InputEvent) -> void:
    if event is InputEventScreenTouch:
        if event.pressed:
            var target := _hit_ui_button(event.position)
            if target != null:
                ui_touch_buttons[event.index] = target
                get_viewport().set_input_as_handled()
        elif ui_touch_buttons.has(event.index):
            var target: Button = ui_touch_buttons[event.index]
            ui_touch_buttons.erase(event.index)
            if target == _hit_ui_button(event.position):
                target.pressed.emit()
            get_viewport().set_input_as_handled()
    elif event is InputEventScreenDrag and ui_touch_buttons.has(event.index):
        get_viewport().set_input_as_handled()
    elif event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
        if event.pressed:
            ui_mouse_button = _hit_ui_button(event.position)
            if ui_mouse_button != null:
                get_viewport().set_input_as_handled()
        elif ui_mouse_button != null:
            var target := ui_mouse_button
            ui_mouse_button = null
            if target == _hit_ui_button(event.position):
                target.pressed.emit()
            get_viewport().set_input_as_handled()