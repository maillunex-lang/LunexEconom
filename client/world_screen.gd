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
    _setup_tutorial()
    _setup_geo_features()
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
        elif not updater.manifest.is_empty() and int(updater.manifest["apk"]["version_code"]) > updater.local_version:
            updater.download_apk()
        else:
            updater.check()
    )
    updater.check()
func set_selection(cell: Vector2i) -> void:
    info.text = "Регион 01 · Участок %d:%d" % [cell.x, cell.y]
    if regional_map_panel != null and regional_map_panel.loaded:
        for city_ref in regional_map_panel.cities:
            if not city_ref is Dictionary:
                continue
            var dx: int = cell.x - int(city_ref.get("x", 0))
            var dy: int = cell.y - int(city_ref.get("y", 0))
            var radius: int = int(city_ref.get("radius", 0))
            if dx * dx + dy * dy <= radius * radius:
                var street_names: Array = city_ref.get("streets", [])
                if not street_names.is_empty():
                    var index := posmod(dx * 13 + dy * 17, street_names.size())
                    info.text = "Участок: %s, %s, %d:%d" % [str(city_ref.get("name", "Город")), str(street_names[index]), cell.x, cell.y]
                break
    if world.build_type.is_empty() and details_panel != null:
        var b: Dictionary = world.building_info(cell)
        if b.is_empty():
            details_panel.hide()
            selected_building = {}
        else:
            selected_building = b
            var own := str(b["owner"]) == GameSession.username and GameSession.username != ""
            var kind_name: String = KIND_NAMES.get(str(b["kind"]), str(b["kind"]))
            details_panel.get_node("VBoxContainer/Title").text = "%s · %s" % [kind_name, "ваша компания" if own else _owner_name(str(b["owner"]))]
            sell_button.visible = own
            sell_button.text = "Продать за %s" % _fmt_money(int(float(building_costs.get(str(b["kind"]), 0)) * sell_rate))
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
var leaderboard_panel
var feed_panel
var stats_actions: HBoxContainer
var section_panel: PanelContainer
var section_title: Label
var section_scroll: ScrollContainer
var section_body: Label
var size_panel: PanelContainer
var pending_size_kind := ""
var catalog_panel: PanelContainer
var placement_panel: PanelContainer
var details_panel: PanelContainer
var sell_button: Button
var selected_building: Dictionary = {}
var sell_rate := 0.5
var sell_pending := false
var catalog_buttons: Array[Button] = []
var ui_pending := false
var build_toolbar: HBoxContainer
var build_hint: Label
var contracts_panel: Control
var contract_shortcut: Control
var tutorial_panel: Control
var regional_map_panel: Control
var perf_overlay: Control
var geo_actions: HBoxContainer
var account_actions: HBoxContainer
var seasons_enabled := true
var rendered_season := -1
var alliance_panel: Control
var messages_panel: Control
var exchange_panel: Control
var charts_panel: Control
var achievements_panel: Control
var social_actions: HBoxContainer
var market_social: HBoxContainer
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
    build_toolbar.add_child(_ui_button("Город", func(): _open_section("Город")))
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
    for entry in [["farm","Ферма 2×2"],["mine","Шахта 2×3"],["factory","Завод 3×2"],["warehouse","Склад 3×3"],["shop","Магазин 2×2"]]:
        var kind: String = entry[0]
        tiles.add_child(_ui_button("%s · %s" % [entry[1], _fmt_money_short(int(building_costs[kind]))], func(): _choose_ui_build(kind), 190))
    content.add_child(_ui_button("Все отрасли (33) · скоро", _open_trade_catalog, 390))
    catalog_panel.hide()
    size_panel = PanelContainer.new()
    size_panel.name = "BuildSizePicker"
    size_panel.add_theme_stylebox_override("panel", _style())
    get_node("UIOverlay").add_child(size_panel)
    var size_content := VBoxContainer.new()
    size_panel.add_child(size_content)
    size_content.add_child(_ui_button("Выберите размер · ×", func(): size_panel.hide(), 280))
    for n in [1, 2, 3]:
        var square_size: int = n
        size_content.add_child(_ui_button("%d×%d" % [n, n], func(): _choose_ui_build_size(pending_size_kind, square_size), 210))
    size_panel.hide()
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
    details_content.name = "VBoxContainer"
    details_panel.add_child(details_content)
    var title := Label.new()
    title.name = "Title"
    details_content.add_child(title)
    sell_button = _ui_button("Продать", _sell_selected)
    details_content.add_child(sell_button)
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
    section_scroll = ScrollContainer.new()
    section_scroll.name = "SectionScroll"
    section_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
    section_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
    section_content.add_child(section_scroll)
    var body_box := VBoxContainer.new()
    body_box.name = "SectionBody"
    body_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    section_scroll.add_child(body_box)
    section_body = Label.new()
    section_body.add_theme_font_size_override("font_size", 18)
    section_body.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    section_body.custom_minimum_size = Vector2(0, 105)
    section_body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    body_box.add_child(section_body)
    section_actions = HBoxContainer.new()
    section_actions.add_child(_ui_button("Взять кредит", _take_loan, 200))
    section_actions.add_child(_ui_button("Погасить кредит", _repay_loan, 200))
    body_box.add_child(section_actions)
    section_actions.hide()
    city_actions = VBoxContainer.new()
    var tax_row := HBoxContainer.new()
    tax_row.add_child(_ui_button("Прибыль −1%", func(): _city_tax_step(-0.01, 0.0), 150))
    tax_row.add_child(_ui_button("Прибыль +1%", func(): _city_tax_step(0.01, 0.0), 150))
    tax_row.add_child(_ui_button("Имущество −0.2%", func(): _city_tax_step(0.0, -0.002), 170))
    tax_row.add_child(_ui_button("Имущество +0.2%", func(): _city_tax_step(0.0, 0.002), 170))
    city_actions.add_child(tax_row)
    var build_row := HBoxContainer.new()
    build_row.add_child(_ui_button("Школа", func(): _start_city_build("school"), 150))
    build_row.add_child(_ui_button("Больница", func(): _start_city_build("hospital"), 150))
    build_row.add_child(_ui_button("Парк", func(): _start_city_build("park"), 150))
    city_actions.add_child(build_row)
    body_box.add_child(city_actions)
    city_actions.hide()
    reg_actions = HBoxContainer.new()
    reg_actions.add_child(_ui_button("Кандидат: 8% / 1%", func(): _city_register(0.08, 0.010), 170))
    reg_actions.add_child(_ui_button("Кандидат: 13% / 2.2%", func(): _city_register(0.13, 0.022), 190))
    reg_actions.add_child(_ui_button("Кандидат: 18% / 2.2%", func(): _city_register(0.18, 0.022), 190))
    body_box.add_child(reg_actions)
    reg_actions.hide()
    vote_actions = HBoxContainer.new()
    body_box.add_child(vote_actions)
    vote_actions.hide()
    var contracts_ui = load("res://contracts_panel.gd").new()
    contracts_ui.name = "ContractsUI"
    add_child(contracts_ui)
    contracts_ui.setup(self)
    stats_actions = HBoxContainer.new()
    stats_actions.add_theme_constant_override("separation", 8)
    stats_actions.add_child(_ui_button("🏆 Рейтинг", func(): _open_stats_panel("leaderboard"), 160))
    stats_actions.add_child(_ui_button("📜 События", func(): _open_stats_panel("feed"), 160))
    body_box.add_child(stats_actions)
    stats_actions.hide()
    geo_actions = HBoxContainer.new()
    geo_actions.add_theme_constant_override("separation", 8)
    geo_actions.add_child(_ui_button("Карта", _open_region_map, 140))
    geo_actions.add_child(_ui_button("Сезоны: вкл", _toggle_seasons, 160))
    geo_actions.add_child(_ui_button("FPS", _toggle_fps, 115))
    body_box.add_child(geo_actions)
    geo_actions.hide()
    account_actions = HBoxContainer.new()
    account_actions.add_child(_ui_button("Выйти из аккаунта", _sign_out_account, 220))
    body_box.add_child(account_actions)
    account_actions.hide()
    social_actions = HBoxContainer.new()
    social_actions.add_theme_constant_override("separation", 8)
    social_actions.add_child(_ui_button("Альянс", func(): _open_social_panel("alliance"), 140))
    social_actions.add_child(_ui_button("Сообщения", func(): _open_social_panel("messages"), 160))
    social_actions.add_child(_ui_button("Звания", func(): _open_social_panel("achievements"), 140))
    body_box.add_child(social_actions)
    social_actions.hide()
    market_social = HBoxContainer.new()
    market_social.add_theme_constant_override("separation", 8)
    market_social.add_child(_ui_button("Биржа", func(): _open_social_panel("exchange"), 140))
    market_social.add_child(_ui_button("Графики", func(): _open_social_panel("charts"), 150))
    body_box.add_child(market_social)
    market_social.hide()
    section_panel.hide()
    _setup_stats_panels()
    _setup_social_panels()
    get_viewport().size_changed.connect(_layout_ui_v1)
    call_deferred("_layout_ui_v1")
    call_deferred("_refresh_announcement")

# ---- Read-only company statistics panels, opened from «Меню». ----
func _setup_stats_panels() -> void:
    leaderboard_panel = load("res://leaderboard_panel.gd").new()
    get_node("UIOverlay").add_child(leaderboard_panel)
    leaderboard_panel.close_requested.connect(func(): leaderboard_panel.hide())
    leaderboard_panel.sort_requested.connect(_refresh_leaderboard)
    feed_panel = load("res://feed_panel.gd").new()
    get_node("UIOverlay").add_child(feed_panel)
    feed_panel.close_requested.connect(func(): feed_panel.hide())
    feed_panel.refresh_requested.connect(_refresh_feed)


func _setup_social_panels() -> void:
    alliance_panel = load("res://alliance_panel.gd").new()
    messages_panel = load("res://messages_panel.gd").new()
    exchange_panel = load("res://exchange_panel.gd").new()
    charts_panel = load("res://charts_panel.gd").new()
    achievements_panel = load("res://achievements_panel.gd").new()
    for panel in [alliance_panel, messages_panel, exchange_panel, charts_panel, achievements_panel]:
        get_node("UIOverlay").add_child(panel)
        panel.bind_host(self)
        panel.close_requested.connect(panel.hide)
        panel.hide()


func _social_by_name(which: String) -> Control:
    match which:
        "alliance":
            return alliance_panel
        "messages":
            return messages_panel
        "exchange":
            return exchange_panel
        "charts":
            return charts_panel
        "achievements":
            return achievements_panel
    return null


func _hide_social_panels() -> void:
    for panel in [alliance_panel, messages_panel, exchange_panel, charts_panel, achievements_panel]:
        if panel != null:
            panel.hide()


func _open_social_panel(which: String) -> void:
    var panel := _social_by_name(which)
    if panel == null:
        return
    world.cancel_build()
    section_panel.hide()
    catalog_panel.hide()
    placement_panel.hide()
    details_panel.hide()
    if contracts_panel != null:
        contracts_panel.hide()
    if leaderboard_panel != null:
        leaderboard_panel.hide()
    if feed_panel != null:
        feed_panel.hide()
    if regional_map_panel != null:
        regional_map_panel.hide()
    _hide_social_panels()
    _show_panel(panel)
    if panel.has_method("refresh"):
        panel.refresh()
    call_deferred("_layout_ui_v1")


func panel_rect(nav_top: float) -> Rect2:
    """Large window between the top HUD and the bottom navigation, inside the safe area (used by all section windows)."""
    var viewport_size := size
    var screen := DisplayServer.screen_get_size()
    var safe := DisplayServer.get_display_safe_area()
    var left_safe := 20.0
    var right_safe := 20.0
    if OS.has_feature("mobile") and screen.x > 0 and safe.size.x > 0:
        left_safe = maxf(left_safe, safe.position.x * viewport_size.x / screen.x + 12.0)
        right_safe = maxf(right_safe, (screen.x - safe.end.x) * viewport_size.x / screen.x + 12.0)
    var width := minf(760.0, viewport_size.x - left_safe - right_safe)
    var top := 66.0
    var height := maxf(180.0, nav_top - 10.0 - top)
    return Rect2(Vector2(maxf(left_safe, (viewport_size.x - width) * 0.5), top), Vector2(width, height))


func _layout_stats_panel(panel: Control, viewport_size: Vector2, nav_top: float) -> void:
    var area := panel_rect(nav_top)
    panel.custom_minimum_size = area.size
    panel.size = area.size
    panel.position = area.position


func _open_stats_panel(which: String) -> void:
    world.cancel_build()
    section_panel.hide()
    catalog_panel.hide()
    placement_panel.hide()
    details_panel.hide()
    leaderboard_panel.hide()
    feed_panel.hide()
    if regional_map_panel != null: regional_map_panel.hide()
    _hide_social_panels()
    if which == "leaderboard":
        _show_panel(leaderboard_panel)
        _refresh_leaderboard("networth")
    elif which == "feed":
        _show_panel(feed_panel)
        _refresh_feed()
    call_deferred("_layout_ui_v1")


func _stats_request(path: String, callback: Callable) -> void:
    if not GameSession.is_authenticated():
        callback.call(false, {})
        return
    var request := HTTPRequest.new()
    request.timeout = 8.0
    add_child(request)
    request.request_completed.connect(func(result: int, status: int, _headers: PackedStringArray, data: PackedByteArray) -> void:
        request.queue_free()
        var parsed = JSON.parse_string(data.get_string_from_utf8())
        callback.call(result == HTTPRequest.RESULT_SUCCESS and status == 200 and parsed is Dictionary,
            parsed if parsed is Dictionary else {})
    )
    var headers := PackedStringArray(["Authorization: Bearer " + GameSession.access_token])
    if request.request(API_ROOT + path, headers) != OK:
        request.queue_free()
        callback.call(false, {})


func _refresh_leaderboard(sort_by: String = "networth") -> void:
    if leaderboard_panel == null:
        return
    leaderboard_panel.show_loading()
    _stats_request("leaderboard?by=" + sort_by, func(ok: bool, data: Dictionary) -> void:
        if ok:
            leaderboard_panel.render(data)
        else:
            leaderboard_panel.show_error()
    )


func _refresh_feed() -> void:
    if feed_panel == null:
        return
    feed_panel.show_loading()
    _stats_request("feed?after=0", func(ok: bool, data: Dictionary) -> void:
        if ok:
            feed_panel.render(data)
        else:
            feed_panel.show_error()
    )

func _layout_ui_v1(override_size: Vector2 = Vector2.ZERO) -> void:
    var size := override_size if override_size != Vector2.ZERO else get_viewport_rect().size
    var usable_width := size.x - 40.0
    catalog_panel.size.x = minf(565.0, usable_width)
    if size_panel != null: size_panel.size.x = minf(330.0, usable_width)
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
    if size_panel != null: size_panel.position = Vector2((size.x - size_panel.size.x) * 0.5, maxf(65, nav_top - size_panel.size.y - 12))
    details_panel.position = Vector2(size.x - details_panel.size.x - 22, maxf(85, (size.y - details_panel.size.y) * 0.5))
    if section_panel != null:
        var area := panel_rect(nav_top)
        section_panel.custom_minimum_size = area.size
        section_panel.size = area.size
        section_panel.position = area.position
    if leaderboard_panel != null:
        _layout_stats_panel(leaderboard_panel, size, nav_top)
    if feed_panel != null:
        _layout_stats_panel(feed_panel, size, nav_top)
    if regional_map_panel != null: regional_map_panel._place()
    for panel in [alliance_panel, messages_panel, exchange_panel, charts_panel, achievements_panel]:
        if panel != null:
            _layout_stats_panel(panel, size, nav_top)

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
    if contracts_panel != null:
        contracts_panel.hide()
    if leaderboard_panel != null: leaderboard_panel.hide()
    if feed_panel != null: feed_panel.hide()
    if regional_map_panel != null: regional_map_panel.hide()
    _hide_social_panels()
    section_title.text = section
    match section:
        "Город":
            section_body.text = _city_text()
            _refresh_city()
        "Экономика":
            section_body.text = _economy_text()
            _refresh_wallet()
        "Логистика":
            section_body.text = "Маршруты поставок и транспортные задания находятся в разработке. Дорожная сеть доступна на карте."
        "Меню":
            section_body.text = _menu_text()
            _refresh_announcement()
    if tutorial_panel != null:
        if section == "Город": tutorial_panel.notify("city_opened")
        elif section == "Экономика": tutorial_panel.notify("economy_opened")
    if geo_actions != null: geo_actions.visible = section == "Меню"
    if account_actions != null: account_actions.visible = section == "Меню"
    stats_actions.visible = section == "Меню"
    if social_actions != null:
        social_actions.visible = section == "Меню"
    section_actions.visible = section == "Экономика"
    if market_social != null:
        market_social.visible = section == "Экономика"
    if contract_shortcut != null:
        contract_shortcut.visible = section == "Экономика"
    _update_city_actions(section == "Город")
    _show_panel(section_panel)
    call_deferred("_layout_ui_v1")

func _open_trade_catalog() -> void:
    # Read-only catalogue: do not allow placement of unfinished specializations.
    _open_section("Каталог отраслей")
    section_body.text = "Загружаем торговые специализации..."
    var req := HTTPRequest.new()
    req.timeout = 8.0
    add_child(req)
    req.request_completed.connect(func(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
        req.queue_free()
        if not is_instance_valid(section_panel) or not section_panel.visible or section_title.text != "Каталог отраслей":
            return
        if result != HTTPRequest.RESULT_SUCCESS or code != 200:
            section_body.text = "Каталог пока недоступен. Действующие здания доступны через меню «Строить»."
            return
        var data = JSON.parse_string(body.get_string_from_utf8())
        if not data is Dictionary or not data.get("trade_specializations", null) is Array:
            section_body.text = "Сервер вернул некорректный каталог."
            return
        var lines: PackedStringArray = ["Торговые объекты (проектируются)", "Для строительства пока доступны базовые здания.", ""]
        var last_category := ""
        for item in data["trade_specializations"]:
            if not item is Dictionary:
                continue
            var category := str(item.get("category", "Прочее"))
            if category != last_category:
                lines.append("● " + category)
                last_category = category
            lines.append("   • " + str(item.get("name", "Объект")) + " · скоро")
        section_body.text = "\n".join(lines)
    )
    var err := req.request("https://rikagro.ru/lunexeconom/api/construction/catalog")
    if err != OK:
        req.queue_free()
        section_body.text = "Не удалось запросить каталог (код %d)." % err


func _open_catalog() -> void:
    world.cancel_build()
    if regional_map_panel != null: regional_map_panel.hide()
    if contracts_panel != null:
        contracts_panel.hide()
    _show_panel(catalog_panel)
    placement_panel.hide()
    details_panel.hide()
    section_panel.hide()
    if leaderboard_panel != null: leaderboard_panel.hide()
    if feed_panel != null: feed_panel.hide()
    _hide_social_panels()
    call_deferred("_layout_ui_v1")

func _choose_ui_build(kind: String) -> void:
    if kind in ["farm", "mine", "factory", "warehouse", "shop"]:
        pending_size_kind = kind
        for n in [1, 2, 3]:
            var b: Button = size_panel.get_child(0).get_child(n)
            b.visible = n <= (2 if kind == "shop" else 3)
        catalog_panel.hide()
        _show_panel(size_panel)
        call_deferred("_layout_ui_v1")
        return
    _choose_ui_build_size(kind, 0)

func _choose_ui_build_size(kind: String, square_size: int) -> void:
    city_mode = false
    size_panel.hide()
    world.choose_build(kind, square_size)
    catalog_panel.hide()
    _show_panel(placement_panel)
    details_panel.hide()
    build_hint.text = "Выберите участок на карте"
    call_deferred("_layout_ui_v1")

func _cancel_ui_build() -> void:
    city_mode = false
    world.cancel_build()
    placement_panel.hide()
    info.text = "Строительство отменено"

func show_build_preview(result: Dictionary) -> void:
    if result.get("ok", false):
        var road_len: int = (result.get("access", []) as Array).size()
        var base_cost := int(building_costs.get(world.build_type, 0))
        if world.build_square_size > 0:
            var legacy_area := 4
            match world.build_type:
                "mine", "factory": legacy_area = 6
                "warehouse": legacy_area = 9
            var new_area := world.build_square_size * world.build_square_size
            base_cost = int((base_cost * new_area + legacy_area - 1) / legacy_area)
        var total := base_cost + road_len * road_cell_cost
        if city_mode:
            info.text = "Из бюджета: %s (в казне %s)" % [_fmt_money(total), _fmt_money(int(city.get("budget", 0)))]
            if build_hint != null: build_hint.text = info.text
            return
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
    if world.build_square_size > 0:
        payload["size"] = world.build_square_size
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
            var from_budget := city_mode
            city_mode = false
            if from_budget: _refresh_city()
            elif tutorial_panel != null and str(payload.get("kind", "")) == "farm":
                tutorial_panel.notify("farm_built")
            var road_cells := int(data.get("road_cells", 0))
            if data.has("balance") and not from_budget: _set_balance(int(data["balance"]))
            info.text = ("Построено за счёт бюджета: %s" if from_budget else "Построено за %s") % _fmt_money(int(data.get("cost", 0))) + ((" · дорога +%d кл." % road_cells) if road_cells > 0 else "")
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
    var err := req.request(API_ROOT + ("city/build" if city_mode else "build"), headers, HTTPClient.METHOD_POST, JSON.stringify(payload))
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
    for panel in [build_toolbar, catalog_panel, placement_panel, details_panel, section_panel, contracts_panel, leaderboard_panel, feed_panel, tutorial_panel, regional_map_panel, perf_overlay, alliance_panel, messages_panel, exchange_panel, charts_panel, achievements_panel]:
        if panel != null and panel.visible and panel.get_global_rect().has_point(point):
            return true
    return false

# Dedicated touch router for Android: GUI focus can be unavailable on
# canvas-stretched viewports. Only route releases inside the same button.
var ui_touch_buttons: Dictionary = {}
var ui_mouse_button: Button = null
func _ui_panels() -> Array:
    return [catalog_panel, placement_panel, details_panel, section_panel, build_toolbar, contracts_panel, leaderboard_panel, feed_panel, tutorial_panel, regional_map_panel, alliance_panel, messages_panel, exchange_panel, charts_panel, achievements_panel]

func _hit_ui_button(point: Vector2) -> Button:
    for panel in _ui_panels():
        if panel == null or not panel.visible or not panel.get_global_rect().has_point(point):
            continue
        var stack: Array[Node] = [panel]
        while not stack.is_empty():
            var node: Node = stack.pop_back()
            # A hidden container hides its whole subtree: its buttons must not react to touches
            # (a button's own `visible` flag stays true when only the parent is hidden).
            if node is CanvasItem and not (node as CanvasItem).visible:
                continue
            # Content scrolled out of a ScrollContainer is clipped: only the visible part may take touches.
            if node is ScrollContainer and not (node as Control).get_global_rect().has_point(point):
                continue
            if node is Button and node.is_visible_in_tree() and node.get_global_rect().has_point(point):
                return node
            for child in node.get_children():
                stack.append(child)
    return null

func _scroll_at(point: Vector2) -> ScrollContainer:
    """The visible ScrollContainer under the point, if any (its content is scrolled by our own touch handling)."""
    for panel in _ui_panels():
        if panel == null or not panel.visible or not panel.get_global_rect().has_point(point):
            continue
        var stack: Array[Node] = [panel]
        while not stack.is_empty():
            var node: Node = stack.pop_back()
            if node is CanvasItem and not (node as CanvasItem).visible:
                continue
            if node is ScrollContainer and (node as Control).get_global_rect().has_point(point):
                return node
            for child in node.get_children():
                stack.append(child)
    return null

const TAP_SLOP := 14.0
var ui_touch_scroll := {}      # touch index -> ScrollContainer or null
var ui_touch_start := {}       # touch index -> start position
var ui_touch_moved := {}       # touch index -> true once the finger moved more than TAP_SLOP

func _input(event: InputEvent) -> void:
    # Android canvas-stretched GUI can miss gestures; route map touches explicitly.
    if regional_map_panel != null and regional_map_panel.visible and regional_map_panel.map_canvas != null:
        if event is InputEventScreenTouch or event is InputEventScreenDrag:
            var surface: Control = regional_map_panel.map_canvas
            if surface.get_global_rect().has_point(event.position) or regional_map_panel.fingers.has(event.index):
                regional_map_panel.map_input(event)
                get_viewport().set_input_as_handled()
                return
    if event is InputEventScreenTouch:
        if event.pressed:
            var target := _hit_ui_button(event.position)
            var scroll := _scroll_at(event.position)
            if target != null or scroll != null:
                ui_touch_buttons[event.index] = target
                ui_touch_scroll[event.index] = scroll
                ui_touch_start[event.index] = event.position
                ui_touch_moved[event.index] = false
                get_viewport().set_input_as_handled()
        elif ui_touch_start.has(event.index):
            var target: Button = ui_touch_buttons.get(event.index)
            var moved: bool = ui_touch_moved.get(event.index, false)
            ui_touch_buttons.erase(event.index)
            ui_touch_scroll.erase(event.index)
            ui_touch_start.erase(event.index)
            ui_touch_moved.erase(event.index)
            if not moved and target != null and target == _hit_ui_button(event.position):
                target.pressed.emit()
            get_viewport().set_input_as_handled()
    elif event is InputEventScreenDrag and ui_touch_start.has(event.index):
        if not ui_touch_moved[event.index] and (event.position - ui_touch_start[event.index]).length() > TAP_SLOP:
            ui_touch_moved[event.index] = true         # a drag is never a tap
        if ui_touch_moved[event.index]:
            var scroll: ScrollContainer = ui_touch_scroll.get(event.index)
            if scroll != null:
                scroll.scroll_vertical = maxi(0, scroll.scroll_vertical - int(event.relative.y))
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
var building_costs := {"farm": 120000, "mine": 300000, "factory": 450000, "warehouse": 80000, "shop": 160000, "school": 400000, "hospital": 800000, "park": 150000}
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
var tax_view: Dictionary = {}
var loan: Dictionary = {}
var loan_pending := false
var section_actions: HBoxContainer
var city_actions: VBoxContainer
var reg_actions: HBoxContainer
var vote_actions: HBoxContainer
var city: Dictionary = {}
var city_mode := false
const LOAN_STEP := 100000
var seen_bankruptcy_month = null
var seen_missed := 0
const KIND_NAMES := {"house": "Жилой дом", "farm": "Ферма", "mine": "Шахта", "factory": "Завод", "warehouse": "Склад", "shop": "Магазин", "school": "Школа", "hospital": "Больница", "park": "Парк"}
var production := {"farm": {"product_id": "honey", "output": 100, "unit_price": 200, "upkeep": 2000, "jobs": 4}, "mine": {"product_id": "oil", "output": 40, "unit_price": 1500, "upkeep": 15000, "jobs": 10}, "factory": {"product_id": "goods", "output": 60, "unit_price": 2000, "upkeep": 26000, "jobs": 20, "inputs": {"oil": 10, "honey": 20}}, "warehouse": {"product_id": "", "output": 0, "unit_price": 0, "upkeep": 2000, "jobs": 2, "capacity": 400}, "shop": {"product_id": "", "output": 0, "unit_price": 0, "upkeep": 3000, "jobs": 5, "retail_hint": 18000}}
var retail_view: Dictionary = {}

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
    profit += int(p.get("retail_hint", 0))
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
    # Profit tax and monthly property tax (rates come from the server; taxes are off when the view is empty)
    if not tax_view.is_empty() and bool(tax_view.get("enabled", true)):
        profit -= int(maxf(float(profit), 0.0) * float(tax_view.get("profit_tax", 0.0)))
        profit -= int(float(building_costs.get(kind, 0)) * float(tax_view.get("property_tax", 0.0)) / 12.0)
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
        lines.append("Прогноз в месяц: доход %s, сырьё %s, зарплаты и обслуживание %s, налоги %s, прибыль после налогов %s (зданий: %d)" % [
            _fmt_money(int(wallet_forecast.get("revenue", 0))), _fmt_money(int(wallet_forecast.get("input_cost", 0))), _fmt_money(int(wallet_forecast.get("upkeep", 0))),
            _fmt_money(int(wallet_forecast.get("profit_tax", 0)) + int(wallet_forecast.get("property_tax", 0))),
            _fmt_money(int(wallet_forecast.get("profit_after_tax", wallet_forecast.get("profit", 0)))), int(wallet_forecast.get("buildings", 0))])
        if int(wallet_forecast.get("owner_spend", 0)) > 0:
            lines.append("Личные траты владельца: около %s в месяц (%d%% прибыли после налогов возвращается на рынок)" % [_fmt_money(int(wallet_forecast.get("owner_spend", 0))), int(round(float(wallet_forecast.get("owner_spend_share", 0.0)) * 100.0))])
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
                lines.append("%s: +%s − %s − %s = %s%s" % [_month_label(int(r.get("month_index", 0))), _fmt_money(int(r.get("revenue", 0))), _fmt_money(int(r.get("input_cost", 0))), _fmt_money(int(r.get("upkeep", 0))), _fmt_money(int(r.get("profit", 0))), (" · личные траты %s" % _fmt_money(int(r.get("owner_spent", 0)))) if int(r.get("owner_spent", 0)) > 0 else ""])
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
    lines.append_array(_tax_lines())
    if not loan.is_empty() and (int(loan.get("balance", 0)) > 0 or int(loan.get("limit", 0)) > 0):
        lines.append("Кредит: %s из лимита %s (под залог зданий), проценты %s/мес (%.1f%%)%s" % [_fmt_money(int(loan.get("balance", 0))), _fmt_money(int(loan.get("limit", 0))), _fmt_money(int(loan.get("monthly_interest", 0))),
            float(loan.get("interest_rate", 0.015)) * 100.0, " — выдача закрыта: есть долги" if bool(loan.get("in_default", false)) else ""])
        if str(loan.get("limit_reason", "")) != "":
            lines.append(str(loan.get("limit_reason", "")))
    if not retail_view.is_empty():
        lines.append("Розница: наценка %d%%, магазины %d, спрос жителей %d ед., не покрыто %d" % [int(round(float(retail_view.get("markup", 0.0)) * 100.0)), int(retail_view.get("shops", 0)), int(retail_view.get("consumer_demand", 0)), int(retail_view.get("unmet_units", 0))])
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
        lines.append("Долги: %s (зарплаты %s, налоги %s, сырьё %s, обслуживание %s)" % [_fmt_money(arrears), _fmt_money(int(company.get("wages_owed", 0))), _fmt_money(int(company.get("tax_owed", 0))), _fmt_money(int(company.get("input_owed", 0))), _fmt_money(int(company.get("maint_owed", 0)))])
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

func _tax_lines() -> PackedStringArray:
    var lines: PackedStringArray = []
    if tax_view.is_empty() or not bool(tax_view.get("enabled", true)): return lines
    var vat = tax_view.get("vat", {})
    var vat_parts: PackedStringArray = []
    for pid in ["honey", "oil", "goods"]:
        if vat is Dictionary and vat.has(pid):
            vat_parts.append("%s %d%%" % [str(market_quotes[pid].get("name", pid)) if market_quotes.has(pid) else pid, int(round(float(vat[pid]) * 100.0))])
    lines.append("Налоги: прибыль %s%%, имущество %s%% в год, НДС: %s" % [_pct(float(tax_view.get("profit_tax", 0.0))), _pct(float(tax_view.get("property_tax", 0.0))), ", ".join(vat_parts)])
    return lines

func _pct(rate: float) -> String:
    var v := rate * 100.0
    return str(int(v)) if absf(v - round(v)) < 0.05 else "%.1f" % v

func _holdings_text(h) -> String:
    if not h is Dictionary or h.is_empty(): return ""
    var parts: PackedStringArray = []
    for kind in ["farm", "mine", "factory", "warehouse", "shop"]:
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

var announcement_text := ""

## Server-wide notice from the administrators (public, plain text, shown in a Label: never interpreted as markup).
func _refresh_announcement() -> void:
    _api_get("announcement", false, func(data: Dictionary) -> void:
        announcement_text = str(data.get("text", "")).strip_edges().substr(0, 200)
        if announcement_text != "":
            info.text = "📢 " + announcement_text
        if section_panel != null and section_panel.visible and section_title.text == "Меню":
            section_body.text = _menu_text()
    )

func _menu_text() -> String:
    var text := "Башкирия: Мёд и Нефть\nВерсия интерфейса 1.0\nУправление: одним пальцем двигайте карту, двумя изменяйте масштаб. Дороги к зданиям прокладываются автоматически."
    if announcement_text != "":
        text += "\n\n📢 Объявление: " + announcement_text
    return text

func _refresh_market() -> void:
    _api_get("market", false, func(data: Dictionary) -> void:
        if data.get("products", null) is Dictionary: market_quotes = data["products"]
        if data.get("competitors", null) is Array: competitors = data["competitors"]
        if data.get("labor", null) is Dictionary: labor = data["labor"]
        if data.get("taxes", null) is Dictionary: tax_view = data["taxes"]
    )

func _refresh_terms() -> void:
    _refresh_market()
    _refresh_city()
    _api_get("world", false, func(data: Dictionary) -> void:
        var eco = data.get("economy", null)
        if not eco is Dictionary: return
        if eco.get("building_costs", null) is Dictionary: building_costs = eco["building_costs"]
        road_cell_cost = int(eco.get("road_cell_cost", road_cell_cost))
        if eco.get("production", null) is Dictionary: production = eco["production"]
        if eco.get("insolvency", null) is Dictionary: sell_rate = float(eco["insolvency"].get("sell_rate", sell_rate))
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
        if data.get("retail", null) is Dictionary: retail_view = data["retail"]
        wallet_forecast = data.get("forecast", {})
        wallet_inventory = data.get("inventory", {})
        wallet_holdings = data.get("holdings", {})
        if data.get("labor", null) is Dictionary: labor = data["labor"]
        if data.get("loan", null) is Dictionary: loan = data["loan"]
        if data.get("taxes", null) is Dictionary: tax_view = data["taxes"]
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
    var seconds_per_month := maxi(int(game_clock.get("month_seconds", 86400)), 1)
    var elapsed := maxf(Time.get_unix_time_from_system() + clock_offset - float(game_clock.get("epoch", 0)), 0.0)
    var current_month := int(game_clock.get("base_index", 0)) + int(elapsed / seconds_per_month)
    var season := int(load("res://season_visual.gd").season_for_month(current_month))
    if rendered_season != season:
        rendered_season = season
        for chunk in world.active_chunks.values():
            chunk.queue_redraw()

func _owner_name(owner: String) -> String:
    for c in competitors:
        if c is Dictionary and str(c.get("owner", "")) == owner: return str(c.get("name", owner))
    if owner == "city": return "Город"
    if owner.begins_with("town:"):                              # generated houses: "Город Уфа"
        var town_id := owner.trim_prefix("town:")
        if regional_map_panel != null and regional_map_panel.loaded:
            for city_ref in regional_map_panel.cities:
                if city_ref is Dictionary and str(city_ref.get("id", "")) == town_id:
                    return "город " + str(city_ref.get("name", town_id))
        return "город"
    for c in _election().get("candidates", []):
        if c is Dictionary and str(c.get("owner", "")) == owner: return str(c.get("name", owner))
    return owner.trim_prefix("npc:") if owner.begins_with("npc:") else owner

func _api_post(path: String, payload: Dictionary, callback: Callable) -> void:
    """POST JSON to the game server with the account token; callback(code, data) gets the parsed answer ({} on errors)."""
    if not GameSession.is_authenticated():
        info.text = "Сначала войдите в аккаунт"
        return
    var req := HTTPRequest.new()
    req.timeout = 12.0
    add_child(req)
    req.request_completed.connect(func(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
        req.queue_free()
        if result != HTTPRequest.RESULT_SUCCESS:
            callback.call(0, {})
            return
        var data = JSON.parse_string(body.get_string_from_utf8())
        callback.call(code, data if data is Dictionary else {})
    )
    var headers := PackedStringArray(["Content-Type: application/json", "Authorization: Bearer " + GameSession.access_token])
    if req.request(API_ROOT + path, headers, HTTPClient.METHOD_POST, JSON.stringify(payload)) != OK:
        req.queue_free()
        callback.call(0, {})

func _sell_selected() -> void:
    if sell_pending or selected_building.is_empty(): return
    sell_pending = true
    info.text = "Продаём здание..."
    _api_post("sell", {"object_id": selected_building["object_id"], "request_id": _new_build_request_id()}, func(code: int, data: Dictionary) -> void:
        sell_pending = false
        if code == 200 or code == 201:
            for event in data.get("events", []):
                if event is Dictionary: world.apply_server_event(event)
            if data.has("balance"): _set_balance(int(data["balance"]))
            details_panel.hide()
            selected_building = {}
            info.text = "Продано за %s" % _fmt_money(int(data.get("price", 0)))
            _refresh_wallet()
        else:
            var errors := {"not_owner": "Это здание не ваше", "not_found": "Здание уже продано", "unauthorized": "Сессия завершена, войдите снова"}
            info.text = str(errors.get(str(data.get("error", "")), "Не удалось продать (HTTP %d)" % code))
    )

func _take_loan() -> void:
    var available := int(loan.get("available", 0))
    var amount := mini(LOAN_STEP, available)
    if amount < int(loan.get("min", 10000)):
        info.text = "Кредит недоступен: нет свободного лимита (нужен залог — постройте здания)" if not bool(loan.get("in_default", false)) else "Кредит недоступен: сначала погасите долги"
        return
    _loan_request("take", amount)

func _repay_loan() -> void:
    var debt := int(loan.get("balance", 0))
    if debt <= 0:
        info.text = "Кредита нет"
        return
    _loan_request("repay", mini(LOAN_STEP, debt))

func _loan_request(action: String, amount: int) -> void:
    if loan_pending: return
    loan_pending = true
    _api_post("loan", {"action": action, "amount": amount, "request_id": _new_build_request_id()}, func(code: int, data: Dictionary) -> void:
        loan_pending = false
        if code == 200 or code == 201:
            if data.get("loan", null) is Dictionary: loan = data["loan"]
            if data.has("balance"): _set_balance(int(data["balance"]))
            info.text = ("Получен кредит %s" if action == "take" else "Погашено %s") % _fmt_money(amount)
            if section_panel.visible and section_title.text == "Экономика": section_body.text = _economy_text()
        else:
            var errors := {"limit_exceeded": "Превышен кредитный лимит", "in_default": "Есть долги: кредит не выдаётся", "insufficient_funds": "Недостаточно денег для погашения",
                "no_loan": "Кредита нет", "invalid_amount": "Недопустимая сумма", "unauthorized": "Сессия завершена, войдите снова"}
            info.text = str(errors.get(str(data.get("error", "")), "Операция не выполнена (HTTP %d)" % code))
    )

# ---- City government (the mayor, budget, taxes and social services) ----
func _is_mayor() -> bool:
    var m = city.get("mayor", null)
    return m is Dictionary and GameSession.username != "" and str(m.get("owner", "")) == GameSession.username

func _refresh_city() -> void:
    _api_get("city", GameSession.is_authenticated(), func(data: Dictionary) -> void:
        city = data
        if section_panel != null and section_panel.visible and section_title.text == "Город":
            section_body.text = _city_text()
            _update_city_actions(true)
    )

func _election() -> Dictionary:
    var e = city.get("election", {})
    return e if e is Dictionary else {}

func _update_city_actions(in_city_section: bool) -> void:
    var e := _election()
    city_actions.visible = in_city_section and _is_mayor()
    reg_actions.visible = in_city_section and not _is_mayor() and bool(e.get("can_register", false))
    var can_vote := in_city_section and bool(e.get("can_vote", false))
    vote_actions.visible = can_vote
    if can_vote:
        for child in vote_actions.get_children(): child.queue_free()
        for c in e.get("candidates", []):
            if c is Dictionary:
                var owner := str(c.get("owner", ""))
                var mark := "✓ " if str(e.get("my_vote", "")) == owner else ""
                vote_actions.add_child(_ui_button("%s%s" % [mark, str(c.get("name", owner)).left(14)], func(): _city_vote(owner), 150))

func _city_text() -> String:
    if city.is_empty(): return "Загрузка данных города..."
    var lines: PackedStringArray = []
    var m: Dictionary = city.get("mayor", {})
    var who := "вы" if _is_mayor() else str(m.get("name", "—"))
    var perks: Dictionary = city.get("perks", {})
    var served := int(perks.get("terms_served", 0))
    var terms_text := (", сроков подряд %d из %d" % [served, int(perks.get("max_terms", 2))]) if served > 0 else ""
    lines.append("Мэр: %s (срок до %s%s)" % [who, _month_label(int(m.get("term_end_month", 0))), terms_text])
    var rating: Dictionary = city.get("rating", {})
    if not rating.is_empty():
        var streak := int(rating.get("low_streak", 0))
        lines.append("Рейтинг мэра: %d%% (жители %d%%, бизнес %d%%)%s" % [int(round(float(rating.get("total", 0.0)) * 100.0)), int(round(float(rating.get("residents", 0.0)) * 100.0)), int(round(float(rating.get("business", 0.0)) * 100.0)),
            (" — КРИТИЧЕСКИЙ: %d мес. из %d до отставки!" % [streak, int(rating.get("dismiss_after", 3))]) if streak > 0 and not bool(m.get("is_npc", true)) else ""])
    lines.append("Бюджет: %s · налоги за прошлый месяц %s · содержание служб %s/мес" % [_fmt_money(int(city.get("budget", 0))), _fmt_money(int(city.get("collected_last_month", 0))), _fmt_money(int(city.get("services_upkeep", 0)))])
    var t: Dictionary = city.get("taxes", {})
    if not t.is_empty() and bool(t.get("enabled", true)):
        var lim: Dictionary = t.get("limits", {})
        lines.append("Налоги: прибыль %s%% (допустимо %s–%s%%), имущество %s%% в год (до %s%%). НДС задаёт закон." % [_pct(float(t.get("profit_tax", 0.0))), _pct(float(lim.get("profit_tax", [0.05, 0.25])[0])), _pct(float(lim.get("profit_tax", [0.05, 0.25])[1])), _pct(float(t.get("property_tax", 0.0))), _pct(float(lim.get("property_tax", [0.0, 0.022])[1]))])
    var soc: Dictionary = city.get("social", {})
    if not soc.is_empty():
        var counts: Dictionary = soc.get("counts", {})
        var cov: Dictionary = soc.get("coverage", {})
        lines.append("Качество жизни: %d%% (больше выпуск и приток жителей)%s" % [int(round(float(soc.get("quality", 0.0)) * 100.0)), "" if bool(soc.get("funded", true)) else " — службы недофинансированы!"])
        for k in ["school", "hospital", "park"]:
            lines.append("%s: %d шт., охват %d%%, цена %s" % [KIND_NAMES[k], int(counts.get(k, 0)), int(round(float(cov.get(k, 0.0)) * 100.0)), _fmt_money(int(float(city.get("costs", {}).get(k, 0))))])
    var perk_text := _perk_text(perks)
    if _is_mayor():
        lines.append("Вы мэр: налоги можно менять раз в игровой месяц. " + perk_text)
    elif perk_text != "":
        lines.append("Должность мэра: " + perk_text)
    lines.append_array(_election_lines())
    return "\n".join(lines)

func _perk_text(perks: Dictionary) -> String:
    if perks.is_empty(): return ""
    var tiers: PackedStringArray = []
    for t in perks.get("term_bonus", []):
        if t is Array and t.size() == 2: tiers.append("рейтинг от %d%% — %s" % [int(round(float(t[0]) * 100.0)), _fmt_money(int(t[1]))])
    return "зарплата %s в месяц + %s%% собранных налогов; награда республики за срок: %s." % [_fmt_money(int(perks.get("salary", 0))), _pct(float(perks.get("bonus_share", 0.0))), ", ".join(tiers)]

func _election_lines() -> PackedStringArray:
    var lines: PackedStringArray = []
    var e := _election()
    if e.is_empty(): return lines
    lines.append("")
    var phase := str(e.get("phase", "idle"))
    var month_end := int(e.get("election_month", 0))
    if phase == "registration":
        lines.append("ВЫБОРЫ МЭРА: идёт регистрация кандидатов (взнос %s), голосование с %s." % [_fmt_money(int(e.get("fee", 0))), _month_label(int(e.get("voting_start", 0)))])
        lines.append("Баллотироваться могут владельцы бизнеса; программа — налог на прибыль / налог на имущество.")
        if bool(e.get("term_limit_reached", false)): lines.append("Вы управляли городом максимальное число сроков подряд — баллотироваться нельзя.")
    elif phase == "voting":
        lines.append("ВЫБОРЫ МЭРА: голосование до конца %s. Ваш голос весит %d." % [_month_label(month_end - 1), int(e.get("vote_weight", 0))])
    else:
        lines.append("Следующие выборы: регистрация с %s." % _month_label(int(e.get("registration_start", 0))))
    if phase != "idle":
        for c in e.get("candidates", []):
            if c is Dictionary:
                lines.append("• %s: прибыль %s%%, имущество %s%%, соцрасходы %d%% — %s" % [str(c.get("name", "")), _pct(float(c.get("profit_tax", 0.0))), _pct(float(c.get("property_tax", 0.0))), int(round(float(c.get("social_share", 0.0)) * 100.0)), str(c.get("slogan", ""))])
        if str(e.get("my_vote", "")) != "": lines.append("Ваш голос отдан: %s" % _owner_name(str(e["my_vote"])))
    var last = e.get("last_result", null)
    if last is Dictionary:
        lines.append("Итог прошлых выборов (%s): победил %s" % [_month_label(int(last.get("election", 0))), str(last.get("winner_name", ""))])
    return lines

func _city_register(profit: float, prop: float) -> void:
    _api_post("city/candidacy", {"profit_tax": profit, "property_tax": prop, "slogan": "Прибыль %s%%, имущество %s%%" % [_pct(profit), _pct(prop)]}, func(code: int, data: Dictionary) -> void:
        if code == 201:
            info.text = "Вы зарегистрированы кандидатом в мэры"
            _refresh_city()
            _refresh_wallet()
        else:
            var errors := {"not_registration_period": "Регистрация кандидатов закрыта", "already_registered": "Вы уже зарегистрированы", "no_company": "Баллотироваться могут владельцы бизнеса",
                "insufficient_funds": "Не хватает денег на взнос кандидата", "out_of_limits": "Программа вне допустимых пределов", "unauthorized": "Сессия завершена, войдите снова"}
            info.text = str(errors.get(str(data.get("error", "")), "Не удалось зарегистрироваться (HTTP %d)" % code))
    )

func _city_vote(candidate: String) -> void:
    _api_post("city/vote", {"candidate": candidate}, func(code: int, data: Dictionary) -> void:
        if code == 200:
            info.text = "Голос принят: %s" % _owner_name(candidate)
            _refresh_city()
        else:
            var errors := {"not_voting_period": "Голосование сейчас закрыто", "unknown_candidate": "Нет такого кандидата", "no_company": "Голосуют владельцы бизнеса", "unauthorized": "Сессия завершена, войдите снова"}
            info.text = str(errors.get(str(data.get("error", "")), "Не удалось проголосовать (HTTP %d)" % code))
    )

func _city_tax_step(d_profit: float, d_property: float) -> void:
    if not _is_mayor(): return
    var t: Dictionary = city.get("taxes", {})
    if t.is_empty(): return
    var lim: Dictionary = t.get("limits", {})
    var profit := clampf(snappedf(float(t.get("profit_tax", 0.13)) + d_profit, 0.001), float(lim.get("profit_tax", [0.05, 0.25])[0]), float(lim.get("profit_tax", [0.05, 0.25])[1]))
    var prop := clampf(snappedf(float(t.get("property_tax", 0.022)) + d_property, 0.001), float(lim.get("property_tax", [0.0, 0.022])[0]), float(lim.get("property_tax", [0.0, 0.022])[1]))
    _api_post("city/taxes", {"profit_tax": profit, "property_tax": prop}, func(code: int, data: Dictionary) -> void:
        if code == 200:
            info.text = "Налоги изменены: прибыль %s%%, имущество %s%%" % [_pct(profit), _pct(prop)]
            _refresh_city()
            _refresh_terms()
        else:
            var errors := {"cooldown": "Налоги можно менять раз в игровой месяц", "out_of_limits": "Ставка вне допустимых пределов", "not_mayor": "Вы не мэр", "unauthorized": "Сессия завершена, войдите снова"}
            info.text = str(errors.get(str(data.get("error", "")), "Не удалось изменить налоги (HTTP %d)" % code))
    )

func _start_city_build(kind: String) -> void:
    if not _is_mayor(): return
    city_mode = true
    world.choose_build(kind)
    section_panel.hide()
    _show_panel(placement_panel)
    build_hint.text = "Выберите участок для: %s (оплата из бюджета)" % KIND_NAMES[kind]
    call_deferred("_layout_ui_v1")

# Additive onboarding hook. Steps advance only on real UI/server events.
func _setup_tutorial() -> void:
    tutorial_panel = load("res://tutorial.gd").new()
    tutorial_panel.setup(self, GameSession.username if GameSession.is_authenticated() else "")


# Additive regional map, optional seasonal colors and FPS diagnostics.
func _setup_geo_features() -> void:
    var file := FileAccess.open("user://season_effects.txt", FileAccess.READ)
    if file != null:
        seasons_enabled = file.get_as_text().strip_edges() != "off"
        file.close()
    regional_map_panel = load("res://regional_map_panel.gd").new()
    regional_map_panel.setup(self)
    perf_overlay = load("res://perf_overlay.gd").new()
    perf_overlay.setup(self)
    if geo_actions != null:
        (geo_actions.get_child(1) as Button).text = "Сезоны: вкл" if seasons_enabled else "Сезоны: выкл"

func _open_region_map() -> void:
    if regional_map_panel != null:
        _hide_social_panels()
        regional_map_panel.open_panel()

func goto_geo_city(city: Dictionary) -> void:
    var x: int = int(city.get("x", 0))
    var y: int = int(city.get("y", 0))
    # The geography overlay never changes build permissions or terrain.
    world.expansion_radius = maxi(world.expansion_radius, maxi(absi(x), absi(y)) + 48)
    world.target_position = world.iso(float(x), float(y))
    world.camera.position = world.target_position
    world._update_visible_chunks()
    info.text = "Переход: " + str(city.get("name", "Город"))

func _toggle_seasons() -> void:
    seasons_enabled = not seasons_enabled
    var file := FileAccess.open("user://season_effects.txt", FileAccess.WRITE)
    if file != null:
        file.store_string("on" if seasons_enabled else "off")
        file.close()
    (geo_actions.get_child(1) as Button).text = "Сезоны: вкл" if seasons_enabled else "Сезоны: выкл"
    for chunk in world.active_chunks.values():
        chunk.queue_redraw()

## Leave this account on this device: end the server session (best effort), forget the remembered login, back to the entry screen.
func _sign_out_account() -> void:
    var token := GameSession.access_token
    if token != "":
        var req := HTTPRequest.new()
        req.timeout = 4.0
        add_child(req)
        var headers := PackedStringArray(["Authorization: Bearer " + token, "Content-Type: application/json"])
        if req.request(API_ROOT + "auth/logout", headers, HTTPClient.METHOD_POST, "{}") == OK:
            await req.request_completed
        req.queue_free()
    GameSession.sign_out()
    get_tree().change_scene_to_file("res://main.tscn")

func _toggle_fps() -> void:
    if perf_overlay != null:
        perf_overlay.toggle()


func geo_month_index() -> int:
    if game_clock.is_empty():
        return 0
    var span := maxi(int(game_clock.get("month_seconds", 86400)), 1)
    var elapsed := maxf(Time.get_unix_time_from_system() + clock_offset - float(game_clock.get("epoch", 0)), 0.0)
    return int(game_clock.get("base_index", 0)) + int(elapsed / span)
