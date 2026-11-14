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
    _refresh_terms()
    _refresh_wallet()
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
    var tiles := GridContainer.new()
    tiles.columns = 2
    content.add_child(tiles)
    for entry in [["farm","Ферма 2×2"],["mine","Шахта 2×3"],["factory","Завод 3×2"],["warehouse","Склад 3×3"]]:
        var kind: String = entry[0]
        tiles.add_child(_ui_button("%s · %s" % [entry[1], _fmt_money_short(int(building_costs[kind]))], func(): _choose_ui_build(kind), 190))
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
    money.tooltip_text = "Баланс компании"
    money.add_theme_font_size_override("font_size", 18)
    top.add_child(money)
    top.move_child(money, 1)
    var date_label := Label.new()
    date_label.name = "GameDate"
    date_label.text = "— —"
    date_label.tooltip_text = "Игровая дата (1 игровой месяц идёт по серверным часам)"
    date_label.add_theme_font_size_override("font_size", 16)
    top.add_child(date_label)
    top.move_child(date_label, 1)
    var date_timer := Timer.new()
    date_timer.wait_time = 1.0
    date_timer.autostart = true
    date_timer.timeout.connect(_tick_game_date)
    add_child(date_timer)
    var resync := Timer.new()
    resync.wait_time = 60.0
    resync.autostart = true
    resync.timeout.connect(func() -> void:
        _refresh_terms()
        _refresh_wallet()
    )
    add_child(resync)

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
            section_body.text = _economy_text()
            _refresh_wallet()
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
        var total := int(building_costs.get(world.build_type, 0)) + road_len * road_cell_cost
        var text := "Цена %s" % _fmt_money(total)
        if road_len > 0: text += " (с дорогой %d кл.)" % road_len
        var per_month := _month_profit(world.build_type)
        text += " · %s%s/мес" % ["+" if per_month >= 0 else "", _fmt_money(per_month)]
        var warning := _supplier_warning(world.build_type)
        if warning != "": text += " · " + warning
        if wallet_balance >= 0 and total > wallet_balance:
            text += " · не хватает %s" % _fmt_money(total - wallet_balance)
        info.text = text

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
    if not GameSession.is_authenticated():
        info.text = "Сначала войдите в аккаунт"
        return
    if world.build_type.is_empty() or world.selected == Vector2i(-1, -1):
        info.text = "Выберите место строительства"
        return
    # Preview is advisory only. Server is the final authority.
    var request_id := _new_build_request_id()
    var payload := {"kind": world.build_type, "x": world.selected.x, "y": world.selected.y, "request_id": request_id}
    ui_pending = true
    info.text = "Проверяем строительство на сервере..."
    var req := HTTPRequest.new()
    req.timeout = 12.0
    add_child(req)
    req.request_completed.connect(func(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
        ui_pending = false
        req.queue_free()
        if result != HTTPRequest.RESULT_SUCCESS:
            info.text = "Нет соединения. Повторите попытку после подключения"
            return
        var data = JSON.parse_string(body.get_string_from_utf8())
        if not data is Dictionary:
            info.text = "Некорректный ответ сервера"
            return
        if code == 200 or code == 201:
            if not bool(data.get("ok", false)):
                info.text = "Сервер не подтвердил строительство"
                return
            for event in data.get("events", []):
                if event is Dictionary:
                    world.apply_server_event(event)
            world.cancel_build()
            placement_panel.hide()
            var road_cells := int(data.get("road_cells", 0))
            if data.has("balance"): _set_balance(int(data["balance"]))
            info.text = "Построено за %s" % _fmt_money(int(data.get("cost", 0))) + ((" · дорога +%d кл." % road_cells) if road_cells > 0 else "")
        else:
            var errors := {"occupied":"Участок уже занят", "invalid_build":"Неверное место или тип здания", "outside_world":"За пределами карты", "unauthorized":"Сессия завершена, войдите снова", "invalid_request_id":"Ошибка команды строительства", "water":"Нельзя строить на воде", "road_overlap":"Нельзя строить на дороге", "no_road_access":"Дорогу к участку проложить нельзя"}
            if str(data.get("error", "")) == "insufficient_funds":
                _set_balance(int(data.get("balance", wallet_balance)))
                info.text = "Недостаточно средств: нужно %s, на счёте %s" % [_fmt_money(int(data.get("cost", 0))), _fmt_money(int(data.get("balance", 0)))]
            else:
                info.text = str(errors.get(str(data.get("error", "")), "Сервер отклонил строительство (HTTP %d)" % code))
            if build_hint != null: build_hint.text = info.text
    )
    var headers := PackedStringArray(["Content-Type: application/json", "Authorization: Bearer " + GameSession.access_token])
    var err := req.request("https://rikagro.ru/lunexeconom/api/build", headers, HTTPClient.METHOD_POST, JSON.stringify(payload))
    if err != OK:
        ui_pending = false
        req.queue_free()
        info.text = "Не удалось отправить запрос: %d" % err

func _new_build_request_id() -> String:
    var crypto := Crypto.new()
    var bytes := crypto.generate_random_bytes(16)
    bytes[6] = (bytes[6] & 15) | 64
    bytes[8] = (bytes[8] & 63) | 128
    var hex := bytes.hex_encode()
    return "%s-%s-%s-%s-%s" % [hex.substr(0,8),hex.substr(8,4),hex.substr(12,4),hex.substr(16,4),hex.substr(20,12)]

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

# ---- Economy (server-authoritative; the client only displays) ----
const API_ROOT := "https://rikagro.ru/lunexeconom/api/"
var building_costs := {"farm": 120000, "mine": 300000, "factory": 450000, "warehouse": 80000}
var road_cell_cost := 5000
var wallet_balance := -1
var wallet_transactions: Array = []
var wallet_reports: Array = []
var wallet_forecast: Dictionary = {}
var wallet_inventory: Dictionary = {}
var market_quotes: Dictionary = {}
var competitors: Array = []
var wallet_holdings: Dictionary = {}
var labor: Dictionary = {}
var company: Dictionary = {}
var seen_bankruptcy_month = null
var seen_missed := 0
const KIND_NAMES := {"farm": "Ферма", "mine": "Шахта", "factory": "Завод", "warehouse": "Склад"}
var production := {"farm": {"product_id": "honey", "output": 100, "unit_price": 200, "upkeep": 2000, "jobs": 4}, "mine": {"product_id": "oil", "output": 40, "unit_price": 1500, "upkeep": 15000, "jobs": 10}, "factory": {"product_id": "goods", "output": 60, "unit_price": 2000, "upkeep": 26000, "jobs": 20, "inputs": {"oil": 10, "honey": 20}}, "warehouse": {"product_id": "", "output": 0, "unit_price": 0, "upkeep": 2000, "jobs": 2, "capacity": 400}}

func _fmt_money(value: int) -> String:
    var digits := str(absi(value))
    var out := ""
    for i in digits.length():
        if i > 0 and (digits.length() - i) % 3 == 0: out += " "
        out += digits[i]
    return ("-" if value < 0 else "") + out + " ₽"

func _fmt_money_short(value: int) -> String:
    if value >= 1000 and value % 1000 == 0: return "%d тыс ₽" % (value / 1000)
    return _fmt_money(value)

func _set_balance(value: int) -> void:
    wallet_balance = value
    var label := get_node_or_null("UIOverlay/HUD/Top/Balance") as Label
    if label != null:
        label.text = _fmt_money(value)
        label.tooltip_text = "Баланс компании"

func _month_profit(kind: String) -> int:
    var p = production.get(kind, null)
    if not p is Dictionary: return 0
    var wage := int(labor.get("wage", 1500))
    var staffing := float(labor.get("staffing", 1.0))
    var profit := -(int(p.get("upkeep", 0)) + int(float(p.get("jobs", 0)) * staffing * wage))
    var pid := str(p.get("product_id", ""))
    if pid != "":
        var price := int(p.get("unit_price", 0))
        # Server quote: the price the market would settle at if this building were added.
        if market_quotes.has(pid): price = int(market_quotes[pid].get("price_if_added", price))
        profit += int(float(p.get("output", 0)) * staffing * price)
    var inputs = p.get("inputs", {})
    if inputs is Dictionary:
        for raw in inputs.keys():
            var raw_price := int(market_quotes[raw].get("price", 0)) if market_quotes.has(raw) else 0
            profit -= int(float(inputs[raw]) * staffing) * raw_price
    return profit

func _supplier_warning(kind: String) -> String:
    var p = production.get(kind, null)
    if not p is Dictionary or not p.get("inputs", null) is Dictionary: return ""
    var missing: PackedStringArray = []
    for raw in p["inputs"].keys():
        if market_quotes.has(raw) and int(market_quotes[raw].get("supply", 0)) <= 0:
            missing.append(str(market_quotes[raw].get("name", raw)))
    return "" if missing.is_empty() else "нет поставщиков: " + ", ".join(missing)

func _market_lines() -> PackedStringArray:
    var lines: PackedStringArray = []
    for pid in market_quotes.keys():
        var q: Dictionary = market_quotes[pid]
        var ref := maxi(int(q.get("reference_price", 1)), 1)
        var price := int(q.get("price", 0))
        var arrow := ""
        if q.get("previous_price", null) != null:
            var prev := int(q["previous_price"])
            arrow = " ▲" if price > prev else (" ▼" if price < prev else " ＝")
        lines.append("%s: %s (%+d%% к базе)%s · предложение %d / спрос %d" % [str(q.get("name", pid)), _fmt_money(price), (price - ref) * 100 / ref, arrow, int(q.get("supply", 0)), int(q.get("demand", 0))])
    return lines

func _economy_text() -> String:
    if wallet_balance < 0:
        return "Загрузка данных счёта..." if GameSession.is_authenticated() else "Войдите в аккаунт, чтобы увидеть баланс."
    var lines: PackedStringArray = ["Баланс: %s" % _fmt_money(wallet_balance)]
    if not wallet_forecast.is_empty():
        lines.append("Прогноз в месяц: доход %s, сырьё %s, зарплаты и обслуживание %s, прибыль %s (зданий: %d)" % [
            _fmt_money(int(wallet_forecast.get("revenue", 0))), _fmt_money(int(wallet_forecast.get("input_cost", 0))), _fmt_money(int(wallet_forecast.get("upkeep", 0))),
            _fmt_money(int(wallet_forecast.get("profit", 0))), int(wallet_forecast.get("buildings", 0))])
    var capacity := int(wallet_inventory.get("capacity", 0))
    if capacity > 0:
        var parts: PackedStringArray = []
        for item in wallet_inventory.get("items", []):
            if item is Dictionary: parts.append("%s %d" % [str(item.get("name", "")), int(item.get("qty", 0))])
        lines.append("Склад: %d / %d ед.%s" % [int(wallet_inventory.get("used", 0)), capacity, (" (" + ", ".join(parts) + ")") if not parts.is_empty() else ""])
    if not wallet_reports.is_empty():
        lines.append("")
        lines.append("Итоги месяцев:")
        for r in wallet_reports.slice(0, 3):
            if r is Dictionary:
                lines.append("%s: +%s − %s − %s = %s" % [_month_label(int(r.get("month_index", 0))), _fmt_money(int(r.get("revenue", 0))), _fmt_money(int(r.get("input_cost", 0))), _fmt_money(int(r.get("upkeep", 0))), _fmt_money(int(r.get("profit", 0)))])
    elif not wallet_transactions.is_empty():
        lines.append("")
        for tx in wallet_transactions.slice(0, 3):
            if tx is Dictionary:
                lines.append("%s%s  %s" % ["+" if int(tx.get("amount", 0)) >= 0 else "", _fmt_money(int(tx.get("amount", 0))), str(tx.get("memo", ""))])
    if not labor.is_empty():
        lines.append("Город: %d жителей, рабочих %d, мест %d, зарплата %s%s" % [int(labor.get("population", 0)), int(labor.get("labor_force", 0)), int(labor.get("jobs", 0)), _fmt_money(int(labor.get("wage", 0))),
            " (нехватка рабочих)" if float(labor.get("staffing", 1.0)) < 1.0 else (" (безработица %d%%)" % int(float(labor.get("unemployment", 0.0)) * 100.0) if float(labor.get("unemployment", 0.0)) > 0.05 else "")])
    var mine := _holdings_text(wallet_holdings)
    if mine != "": lines.append("Мои здания: " + mine)
    lines.append_array(_company_lines())
    var market := _market_lines()
    if not market.is_empty():
        lines.append("")
        lines.append("Рынок:")
        lines.append_array(market)
    if not competitors.is_empty():
        lines.append("")
        lines.append("Конкуренты:")
        for c in competitors:
            if c is Dictionary:
                var held := _holdings_text(c.get("holdings", {}))
                lines.append("%s — %d зд.%s" % [str(c.get("name", "")), int(c.get("buildings", 0)), (" (" + held + ")") if held != "" else ""])
    return "\n".join(lines)

func _company_lines() -> PackedStringArray:
    var lines: PackedStringArray = []
    if company.is_empty(): return lines
    var arrears := int(company.get("arrears", 0))
    if arrears > 0:
        lines.append("Долги: %s (зарплаты %s, сырьё %s, обслуживание %s)" % [_fmt_money(arrears), _fmt_money(int(company.get("wages_owed", 0))), _fmt_money(int(company.get("input_owed", 0))), _fmt_money(int(company.get("maint_owed", 0)))])
    var missed := int(company.get("missed", 0))
    if missed > 0:
        lines.append("ВНИМАНИЕ: расходы не оплачены %d мес. подряд из %d, выпуск снижен, затем банкротство!" % [missed, int(company.get("bankrupt_after", 3))])
    var bankruptcies := int(company.get("bankruptcies", 0))
    if bankruptcies > 0 and company.get("last_bankruptcy_month", null) != null:
        lines.append("Банкротств: %d (последнее: %s)" % [bankruptcies, _month_label(int(company["last_bankruptcy_month"]))])
    return lines

func _announce_company_status() -> void:
    var last = company.get("last_bankruptcy_month", null)
    var missed := int(company.get("missed", 0))
    if last != null and seen_bankruptcy_month != null and int(last) != int(seen_bankruptcy_month):
        info.text = "Компания обанкротилась: здания проданы за 40% стоимости, долги погашены, остаток списан"
    elif missed > seen_missed:
        info.text = "Расходы не оплачены (%d из %d мес.): пополните счёт, иначе банкротство" % [missed, int(company.get("bankrupt_after", 3))]
    seen_bankruptcy_month = last if last != null else -1
    seen_missed = missed

func _holdings_text(h) -> String:
    if not h is Dictionary or h.is_empty(): return ""
    var parts: PackedStringArray = []
    for kind in ["farm", "mine", "factory", "warehouse"]:
        if h.has(kind): parts.append("%s ×%d" % [KIND_NAMES[kind], int(h[kind])])
    return ", ".join(parts)

func _month_label(index: int) -> String:
    return "%s %d" % [MONTH_NAMES[index % 12], 2027 + index / 12]

func _api_get(path: String, auth: bool, callback: Callable) -> void:
    var req := HTTPRequest.new()
    req.timeout = 8.0
    add_child(req)
    req.request_completed.connect(func(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
        req.queue_free()
        if result != HTTPRequest.RESULT_SUCCESS or code != 200: return
        var data = JSON.parse_string(body.get_string_from_utf8())
        if data is Dictionary: callback.call(data)
    )
    var headers := PackedStringArray()
    if auth:
        if not GameSession.is_authenticated():
            req.queue_free()
            return
        headers.append("Authorization: Bearer " + GameSession.access_token)
    if req.request(API_ROOT + path, headers) != OK:
        req.queue_free()

func _refresh_market() -> void:
    _api_get("market", false, func(data: Dictionary) -> void:
        if data.get("products", null) is Dictionary: market_quotes = data["products"]
        if data.get("competitors", null) is Array: competitors = data["competitors"]
        if data.get("labor", null) is Dictionary: labor = data["labor"]
    )

func _refresh_terms() -> void:
    _refresh_market()
    _api_get("world", false, func(data: Dictionary) -> void:
        var eco = data.get("economy", null)
        if not eco is Dictionary: return
        if eco.get("building_costs", null) is Dictionary: building_costs = eco["building_costs"]
        road_cell_cost = int(eco.get("road_cell_cost", road_cell_cost))
        if eco.get("production", null) is Dictionary: production = eco["production"]
        if data.get("clock", null) is Dictionary:
            game_clock = data["clock"]
            clock_offset = float(game_clock.get("server_time", 0)) - Time.get_unix_time_from_system()
            _tick_game_date()
    )

func _refresh_wallet() -> void:
    _api_get("wallet", true, func(data: Dictionary) -> void:
        _set_balance(int(data.get("balance", 0)))
        wallet_transactions = data.get("transactions", [])
        wallet_reports = data.get("reports", [])
        wallet_forecast = data.get("forecast", {})
        wallet_inventory = data.get("inventory", {})
        wallet_holdings = data.get("holdings", {})
        if data.get("labor", null) is Dictionary: labor = data["labor"]
        if data.get("company", null) is Dictionary:
            company = data["company"]
            _announce_company_status()
        if data.get("market", null) is Dictionary: market_quotes = data["market"]
        if section_panel != null and section_panel.visible and section_title.text == "Экономика":
            section_body.text = _economy_text()
    )

# ---- Game calendar (server time is authoritative; the client only displays) ----
const MONTH_NAMES := ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
var game_clock: Dictionary = {}
var clock_offset := 0.0

func _game_date_text(clock: Dictionary, server_now: float) -> String:
    var month_seconds := maxi(int(clock.get("month_seconds", 86400)), 1)
    var elapsed := maxf(server_now - float(clock.get("epoch", 0)), 0.0)
    var index := int(clock.get("base_index", 0)) + int(elapsed / month_seconds)
    var into_month := fmod(elapsed, float(month_seconds))
    var day := mini(int(into_month * 30.0 / month_seconds) + 1, 30)
    return "%d %s %d" % [day, MONTH_NAMES[index % 12], 2027 + index / 12]

func _tick_game_date() -> void:
    if game_clock.is_empty(): return
    var label := get_node_or_null("UIOverlay/HUD/Top/GameDate") as Label
    if label != null:
        label.text = _game_date_text(game_clock, Time.get_unix_time_from_system() + clock_offset)
