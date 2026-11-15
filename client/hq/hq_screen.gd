extends Control
## EX-13. A lightweight 2D headquarters; the 3D world is never a child of this scene.
signal map_requested(cell: Vector2i)
const API = preload("res://hq/hq_api.gd")
const NAV := ["Обзор", "Предприятия", "Склады и логистика", "Финансы", "Недвижимость и земля", "Строительство", "Город", "Рынок и биржа", "Контракты", "Население и спрос", "Настройки"]
const INK := Color("#e7f4e9")
const MUTED := Color("#aec6bb")
const GREEN := Color("#97d6b1")
var data: Dictionary = {}
var current_section := "Обзор"
var sample_mode := false
var poll_timer: Timer
var count_requests := 0
var last_refresh_msec := -15000
var request: HTTPRequest
var waiting := false
var visible_to_user := true
var title_label: Label
var meta_label: Label
var cash_label: Label
var gain_label: Label
var rating_label: Label
var status_label: Label
var content: VBoxContainer
var notifications: VBoxContainer
var nav_buttons: Dictionary = {}
var body_scroll: ScrollContainer
var root_margin: MarginContainer
var header: HBoxContainer
var content_row: HBoxContainer
var left_nav: ScrollContainer
var right_scroll: ScrollContainer
var top_buttons: HBoxContainer
var right_panel: PanelContainer
var _first_view := true
var _last_render_hash := 0
var _desired_focus := Vector2i(-1, -1)
var _last_response: Dictionary = {}
var show_performance := false
var frames_seen := 0
var frame_ms_sum := 0.0
var original_fps := 0
var original_low_processor := false

func _ready() -> void:
    if OS.has_feature("mobile"):
        DisplayServer.screen_set_orientation(DisplayServer.SCREEN_LANDSCAPE)
    sample_mode = API.sample_enabled()
    original_fps = Engine.max_fps
    original_low_processor = OS.low_processor_usage_mode
    _build_ui()
    get_viewport().size_changed.connect(_layout)
    _layout()
    request = HTTPRequest.new()
    request.timeout = 8.0
    add_child(request)
    request.request_completed.connect(_on_hq_response)
    poll_timer = Timer.new()
    poll_timer.name = "HQPoll"
    poll_timer.wait_time = 15.0
    poll_timer.one_shot = false
    poll_timer.timeout.connect(refresh)
    add_child(poll_timer)
    _set_active(true)

func _exit_tree() -> void:
    Engine.max_fps = original_fps
    OS.low_processor_usage_mode = original_low_processor

func _notification(what: int) -> void:
    if what == NOTIFICATION_APPLICATION_PAUSED:
        _set_active(false)
    elif what == NOTIFICATION_APPLICATION_RESUMED:
        _set_active(is_visible_in_tree())

func _visibility_changed() -> void:
    _set_active(is_visible_in_tree())

func _set_active(on: bool) -> void:
    visible_to_user = on
    if on:
        Engine.max_fps = 30
        OS.low_processor_usage_mode = true
        if poll_timer != null and poll_timer.is_stopped():
            poll_timer.start()
        if _first_view:
            _first_view = false
            refresh()
        elif Time.get_ticks_msec() - last_refresh_msec >= 15000:
            refresh()
    else:
        if poll_timer != null:
            poll_timer.stop()
        if request != null and waiting:
            request.cancel_request()
            waiting = false
        Engine.max_fps = original_fps
        OS.low_processor_usage_mode = original_low_processor

func _process(_delta: float) -> void:
    if show_performance:
        frames_seen += 1
        frame_ms_sum += Performance.get_monitor(Performance.TIME_PROCESS) * 1000.0

func refresh() -> void:
    if not visible_to_user or waiting:
        return
    if not sample_mode and not GameSession.is_authenticated():
        status_label.text = "Требуется вход в аккаунт"
        return
    var now := Time.get_ticks_msec()
    if count_requests > 0 and now - last_refresh_msec < 15000:
        return
    last_refresh_msec = now
    count_requests += 1
    if sample_mode:
        apply_hq(API.sample())
        return
    waiting = true
    var err := request.request(API.ROOT + "hq", API.authorize())
    if err != OK:
        waiting = false
        status_label.text = "Сервер штаба недоступен (%d)" % err

func _on_hq_response(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
    waiting = false
    if not visible_to_user:
        return
    if result != HTTPRequest.RESULT_SUCCESS or code != 200:
        status_label.text = "Нет данных /hq (HTTP %d). Проверьте подключение" % code
        return
    var response = JSON.parse_string(body.get_string_from_utf8())
    if response is Dictionary:
        apply_hq(response)
    else:
        status_label.text = "Сервер вернул неверный формат /hq"

func apply_hq(response: Dictionary) -> void:
    data = response
    var hash_value := hash(JSON.stringify(response))
    if hash_value == _last_render_hash:
        return
    _last_render_hash = hash_value
    var company: Dictionary = _dict(response, "company")
    var money: Dictionary = _dict(response, "money")
    var clock: Dictionary = _dict(response, "clock")
    title_label.text = str(company.get("name", "Моя компания")).substr(0, 64)
    var sec: int = maxi(0, int(clock.get("seconds_to_next_month", 0)))
    meta_label.text = "%02d.%04d · до нового месяца %d ч %02d мин" % [int(clock.get("month", 1)), int(clock.get("year", 2027)), sec / 3600, (sec % 3600) / 60]
    cash_label.text = _money(int(money.get("cash", 0)))
    gain_label.text = "%+d ₽ / мес" % int(money.get("profit_month", 0))
    rating_label.text = "★ %d" % int(company.get("rating", 0))
    status_label.text = "Данные: образец" if sample_mode else "Данные сервера"
    _render_section()
    _render_alerts()

func _dict(source: Dictionary, key: String) -> Dictionary:
    var value = source.get(key, {})
    return value if value is Dictionary else {}

func _arr(source: Dictionary, key: String) -> Array:
    var value = source.get(key, [])
    return value if value is Array else []

func _money(value: int) -> String:
    var digits := str(absi(value))
    var formatted := ""
    while digits.length() > 3:
        formatted = " " + digits.substr(digits.length() - 3, 3) + formatted
        digits = digits.substr(0, digits.length() - 3)
    return ("−" if value < 0 else "") + digits + formatted + " ₽"

func _style(fill: Color = Color(0.055, 0.15, 0.14, 0.90), radius: int = 17) -> StyleBoxFlat:
    var style := StyleBoxFlat.new()
    style.bg_color = fill
    style.border_color = Color(0.41, 0.72, 0.56, 0.30)
    style.set_border_width_all(1)
    style.set_corner_radius_all(radius)
    style.set_content_margin_all(13)
    return style

func _panel(parent: Node, minimum: Vector2 = Vector2.ZERO) -> PanelContainer:
    var panel := PanelContainer.new()
    panel.custom_minimum_size = minimum
    panel.add_theme_stylebox_override("panel", _style())
    parent.add_child(panel)
    return panel

func _label(parent: Node, value: String, size: int = 17, color: Color = INK) -> Label:
    var label := Label.new()
    label.text = value
    label.add_theme_color_override("font_color", color)
    label.add_theme_font_size_override("font_size", size)
    label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    parent.add_child(label)
    return label

func _button(parent: Node, value: String, action: Callable, minimum_width: float = 110) -> Button:
    var button := Button.new()
    button.text = value
    button.custom_minimum_size = Vector2(minimum_width, 48)
    button.add_theme_font_size_override("font_size", 16)
    button.add_theme_color_override("font_color", INK)
    button.add_theme_stylebox_override("normal", _style(Color(0.10, 0.25, 0.21, 0.96), 13))
    button.add_theme_stylebox_override("hover", _style(Color(0.18, 0.40, 0.31, 1.0), 13))
    button.add_theme_stylebox_override("pressed", _style(Color(0.24, 0.49, 0.33, 1.0), 13))
    button.pressed.connect(action)
    parent.add_child(button)
    return button

func _build_ui() -> void:
    set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    var backdrop := TextureRect.new()
    backdrop.name = "Illustration"
    backdrop.texture = load("res://hq/art/headquarters.svg")
    backdrop.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
    backdrop.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
    backdrop.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    backdrop.mouse_filter = Control.MOUSE_FILTER_IGNORE
    add_child(backdrop)
    var tint := ColorRect.new()
    tint.color = Color(0.025, 0.09, 0.08, 0.68)
    tint.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    tint.mouse_filter = Control.MOUSE_FILTER_IGNORE
    add_child(tint)
    root_margin = MarginContainer.new()
    root_margin.name = "SafeArea"
    root_margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    add_child(root_margin)
    var main := VBoxContainer.new()
    main.add_theme_constant_override("separation", 10)
    root_margin.add_child(main)
    var top_scroll := ScrollContainer.new()
    top_scroll.name = "HeaderScroll"
    top_scroll.follow_focus = false
    top_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_AUTO
    top_scroll.vertical_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
    top_scroll.scroll_deadzone = 0
    main.add_child(top_scroll)
    top_scroll.custom_minimum_size.y = 80
    top_scroll.clip_contents = true
    top_scroll.size_flags_stretch_ratio = 0.0
    top_scroll.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
    top_scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    var top_panel := _panel(top_scroll)
    top_panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    top_panel.custom_minimum_size.y = 80
    header = HBoxContainer.new()
    header.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    header.alignment = BoxContainer.ALIGNMENT_BEGIN
    header.add_theme_constant_override("separation", 13)
    top_panel.add_child(header)
    header.custom_minimum_size.y = 55
    var identity := VBoxContainer.new()
    identity.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    identity.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
    header.add_child(identity)
    title_label = _label(identity, "МОЯ КОМПАНИЯ", 23, GREEN)
    meta_label = _label(identity, "Подключение...", 13, MUTED)
    var cash_box := VBoxContainer.new()
    cash_box.custom_minimum_size.x = 130
    header.add_child(cash_box)
    cash_box.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
    cash_label = _label(cash_box, "— ₽", 23)
    gain_label = _label(cash_box, "— ₽ / мес", 13, GREEN)
    rating_label = _label(header, "★ —", 20)
    top_buttons = HBoxContainer.new()
    header.add_child(top_buttons)
    top_buttons.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
    _button(top_buttons, "◈ Карта", func(): open_map(), 115)
    _button(top_buttons, "☰ Меню", _open_menu, 110)
    content_row = HBoxContainer.new()
    content_row.size_flags_vertical = Control.SIZE_EXPAND_FILL
    content_row.add_theme_constant_override("separation", 10)
    main.add_child(content_row)
    left_nav = ScrollContainer.new()
    left_nav.name = "NavigationScroll"
    left_nav.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
    content_row.add_child(left_nav)
    var nav_panel := _panel(left_nav)
    var nav_box := VBoxContainer.new()
    nav_box.add_theme_constant_override("separation", 5)
    nav_panel.add_child(nav_box)
    for section in NAV:
        var section_name: String = section
        var button := _button(nav_box, section_name, func(): open_section(section_name), 205)
        nav_buttons[section_name] = button
    body_scroll = ScrollContainer.new()
    body_scroll.name = "ContentScroll"
    body_scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    body_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
    body_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
    content_row.add_child(body_scroll)
    var content_panel := _panel(body_scroll)
    content_panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    content = VBoxContainer.new()
    content.name = "MainCards"
    content.add_theme_constant_override("separation", 12)
    content_panel.add_child(content)
    right_scroll = ScrollContainer.new()
    right_scroll.name = "AlertsScroll"
    right_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
    content_row.add_child(right_scroll)
    right_panel = _panel(right_scroll, Vector2(240, 0))
    notifications = VBoxContainer.new()
    notifications.name = "Alerts"
    notifications.add_theme_constant_override("separation", 9)
    right_panel.add_child(notifications)
    status_label = _label(main, "Ожидаем данные...", 12, MUTED)
    open_section("Обзор")
    _render_alerts()

func _layout() -> void:
    if root_margin == null:
        return
    var view := get_viewport_rect().size
    var screen := DisplayServer.screen_get_size()
    var safe := DisplayServer.get_display_safe_area()
    var edges := [18, 12, 18, 12]
    if OS.has_feature("mobile") and screen.x > 0 and screen.y > 0 and safe.size.x > 0 and safe.size.y > 0:
        edges[0] = maxi(18, int(float(safe.position.x) * view.x / screen.x) + 12)
        edges[1] = maxi(12, int(float(safe.position.y) * view.y / screen.y) + 8)
        edges[2] = maxi(18, int(float(screen.x - safe.end.x) * view.x / screen.x) + 12)
        edges[3] = maxi(12, int(float(screen.y - safe.end.y) * view.y / screen.y) + 8)
    root_margin.add_theme_constant_override("margin_left", edges[0])
    root_margin.add_theme_constant_override("margin_top", edges[1])
    root_margin.add_theme_constant_override("margin_right", edges[2])
    root_margin.add_theme_constant_override("margin_bottom", edges[3])
    var small := view.x < 1020
    if view.y < 450:
        root_margin.add_theme_constant_override("margin_top", 4)
        root_margin.add_theme_constant_override("margin_bottom", 4)
        root_margin.add_theme_constant_override("margin_left", 8)
        root_margin.add_theme_constant_override("margin_right", 8)
    left_nav.custom_minimum_size.x = 155 if small else 215
    right_scroll.custom_minimum_size.x = 0 if small else 240
    right_scroll.visible = not small
    for b in nav_buttons.values():
        (b as Button).custom_minimum_size.x = 145 if small else 205
    title_label.add_theme_font_size_override("font_size", 17 if small else 23)
    cash_label.add_theme_font_size_override("font_size", 18 if small else 23)
    _render_alerts()

func _clear(node: Node) -> void:
    for child in node.get_children():
        node.remove_child(child)
        child.queue_free()

func open_section(section: String) -> void:
    current_section = section
    if content == null:
        return
    for key in nav_buttons:
        var button: Button = nav_buttons[key]
        button.modulate = GREEN if key == section else Color.WHITE
    _render_section()
    body_scroll.scroll_vertical = 0

func _card(heading: String, subtitle: String = "") -> VBoxContainer:
    var panel := _panel(content)
    var box := VBoxContainer.new()
    box.add_theme_constant_override("separation", 8)
    panel.add_child(box)
    _label(box, heading, 20, GREEN)
    if not subtitle.is_empty():
        _label(box, subtitle, 15, MUTED)
    return box

func _render_section() -> void:
    if content == null:
        return
    _clear(content)
    match current_section:
        "Обзор":
            _overview()
        "Предприятия":
            _enterprises()
        "Финансы":
            _finance()
        "Город":
            _endpoint("Город", "city")
        "Рынок и биржа":
            _endpoint("Рынок", "market")
            _endpoint("Биржа", "exchange")
        "Контракты":
            _endpoint("Контракты", "contracts")
        "Настройки":
            _settings()
        "Склады и логистика":
            _soon("Управление складскими запасами и поставками")
        "Недвижимость и земля":
            _soon("Реестр земельных участков и недвижимости")
        "Строительство":
            _projects()
        "Население и спрос":
            _soon("Домохозяйства, спрос и занятость")
        _:
            _soon("Раздел")
    if current_section == "Город":
        _load_endpoint("city")
    elif current_section == "Рынок и биржа":
        _load_endpoint("market")
        _load_endpoint("exchange")
    elif current_section == "Контракты":
        _load_endpoint("contracts")
    elif current_section == "Финансы":
        _load_endpoint("wallet")

func _overview() -> void:
    var money := _dict(data, "money")
    var financial := _card("ДЕНЕЖНЫЙ ПОТОК", "Доход: %s  ·  Расход: %s" % [_money(int(money.get("income_month", 0))), _money(int(money.get("expenses_month", 0)))])
    var row := HBoxContainer.new()
    financial.add_child(row)
    _label(row, "Прибыль: " + _money(int(money.get("profit_month", 0))), 20, GREEN)
    row.add_spacer(false)
    _label(row, "Прогноз: " + _money(int(money.get("forecast_next_month", 0))), 16)
    var chart = load("res://hq/hq_chart.gd").new()
    chart.name = "FinancialChart"
    chart.custom_minimum_size = Vector2(0, 100)
    financial.add_child(chart)
    chart.set_history(_arr(data, "history"))
    _enterprises()
    _projects()
    var f := _dict(data, "finance")
    var box := _card("ФИНАНСЫ", "Налоги к уплате: %s  ·  Просрочки: %s" % [_money(int(f.get("taxes_due", 0))), _money(int(f.get("arrears", 0)))])
    _button(box, "Финансовый кабинет", func(): open_section("Финансы"), 210)
    var city := _dict(data, "city")
    box = _card("ГОРОД", "%s · Население: %d · Рейтинг: %d" % [str(city.get("name", "—")), int(city.get("population", 0)), int(city.get("rating", 0))])
    _button(box, "Открыть город", func(): open_section("Город"), 210)
    var contracts := _dict(data, "contracts")
    box = _card("КОНТРАКТЫ И БИРЖА", "Активных: %d · Доступных: %d · Заявок: %d" % [int(contracts.get("active", 0)), int(contracts.get("open", 0)), int(_dict(data, "exchange").get("open_orders", 0))])
    _button(box, "Контракты", func(): open_section("Контракты"), 180)
    var quotes := _arr(data, "market")
    box = _card("РЫНОК", "Товаров в сводке: %d" % quotes.size())
    _button(box, "Биржа и цены", func(): open_section("Рынок и биржа"), 180)

func _enterprises() -> void:
    var enterprises := _arr(data, "enterprises")
    var box := _card("ПРЕДПРИЯТИЯ  ·  %d" % enterprises.size())
    if enterprises.is_empty():
        _label(box, "Пока нет предприятий. Откройте карту для строительства.", 15, MUTED)
    for entry in enterprises:
        if not entry is Dictionary:
            continue
        var item: Dictionary = entry
        var line := VBoxContainer.new()
        box.add_child(line)
        line.add_theme_constant_override("separation", 5)
        _label(line, str(item.get("name", item.get("kind", "Предприятие"))).substr(0, 70) + " · " + str(item.get("city", "")), 18)
        var status := str(item.get("status", "unknown"))
        if status == "building":
            status = "строится · " + str(item.get("construction_stage", ""))
        elif status == "working":
            status = "работает"
        var stock := _dict(item, "stock")
        var stocks := []
        for good in stock.keys():
            stocks.append("%s: %s" % [str(good), str(stock[good])])
        _label(line, "%s · прибыль: %s · занятость: %.0f%% · склад: %s" % [status, _money(int(item.get("profit_month", 0))), float(item.get("staffing", 0)) * 100.0, ", ".join(stocks) if not stocks.is_empty() else "нет данных"], 14, MUTED)
        var alerts: Array = item.get("alerts", [])
        if alerts is Array and not alerts.is_empty():
            _label(line, "⚠ " + ", ".join(alerts), 13, Color("#f3c884"))
        var controls := HBoxContainer.new()
        line.add_child(controls)
        var target := Vector2i(int(item.get("x", 0)), int(item.get("y", 0)))
        var id := str(item.get("id", ""))
        _button(controls, "◈ На карте", func(): open_map(target), 135)
        _button(controls, "⚙ Управление", func(): _open_enterprise(id, item), 160)
        box.add_child(HSeparator.new())

func _projects() -> void:
    var projects := _arr(data, "projects")
    var box := _card("СТРОИТЕЛЬСТВО  ·  %d" % projects.size())
    if projects.is_empty():
        _label(box, "Активных проектов нет", 15, MUTED)
    for project in projects:
        if not project is Dictionary:
            continue
        _label(box, "%s · %s · готовность %d%%" % [str(project.get("kind", "Проект")), str(project.get("stage", "")), int(project.get("percent", 0))], 15)

func _finance() -> void:
    var f := _dict(data, "finance")
    var box := _card("ФИНАНСЫ", "Сводка штаба и действующий маршрут GET /wallet")
    _label(box, "Налоги: %s · Просрочка: %s · Доступный кредит: %s" % [_money(int(f.get("taxes_due", 0))), _money(int(f.get("arrears", 0))), _money(int(f.get("credit_available", 0)))])
    for loan in _arr(f, "loans"):
        if loan is Dictionary:
            _label(box, "Кредит: остаток %s · платёж %s" % [_money(int(loan.get("balance", 0))), _money(int(loan.get("next_payment", 0)))])
    _endpoint("Текущий кошелёк и операции", "wallet")
    _soon("NPC-банки и дополнительные финансовые инструменты")

func _endpoint(heading: String, path: String) -> void:
    var box := _card(heading, "Данные по действующему маршруту /%s" % path)
    var block := _label(box, "Открывается по запросу...", 15, MUTED)
    block.name = "Endpoint_" + path.replace("/", "_")
    if _last_response.has(path):
        _render_endpoint(path, _last_response[path])

func _load_endpoint(path: String) -> void:
    if sample_mode:
        var fallback := {"notice": "В режиме образца доступны только данные GET /hq. Для API включите сервер."}
        _last_response[path] = fallback
        _render_endpoint(path, fallback)
        return
    if not GameSession.is_authenticated() or not visible_to_user:
        return
    var req := HTTPRequest.new()
    req.timeout = 8.0
    add_child(req)
    req.request_completed.connect(func(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
        req.queue_free()
        if not visible_to_user:
            return
        var response = JSON.parse_string(body.get_string_from_utf8())
        if result == HTTPRequest.RESULT_SUCCESS and code == 200 and response is Dictionary:
            _last_response[path] = response
        else:
            _last_response[path] = {"notice": "Маршрут недоступен (HTTP %d)" % code}
        _render_endpoint(path, _last_response[path])
    )
    var route := "soc/exchange/book?product=honey" if path == "exchange" else path
    var headers := API.authorize() if path != "market" else PackedStringArray()
    if req.request(API.ROOT + route, headers) != OK:
        req.queue_free()

func _render_endpoint(path: String, response: Dictionary) -> void:
    if content == null:
        return
    var block := content.find_child("Endpoint_" + path.replace("/", "_"), true, false) as Label
    if block == null:
        return
    if response.has("notice"):
        block.text = str(response["notice"])
        return
    var lines := PackedStringArray()
    # Preview only. No transaction commands from HQ: the server remains authoritative.
    for key in response.keys():
        var value = response[key]
        if value is Dictionary:
            lines.append("%s: %s" % [str(key), _summary(value)])
        elif value is Array:
            lines.append("%s: %d записей" % [str(key), value.size()])
        else:
            lines.append("%s: %s" % [str(key), str(value)])
        if lines.size() >= 18:
            break
    block.text = "\n".join(lines)

func _summary(source: Dictionary) -> String:
    var parts := PackedStringArray()
    for key in source.keys():
        var value = source[key]
        if not value is Array and not value is Dictionary:
            parts.append("%s=%s" % [str(key), str(value)])
        if parts.size() == 4:
            break
    return "  ·  ".join(parts)

func _soon(value: String) -> void:
    _card(value, "Скоро · экран готов к подключению будущего API по docs/HQ_SCREEN.md")

func _settings() -> void:
    var box := _card("НАСТРОЙКИ И АККАУНТ", "Режим данных влияет только на интерфейс штаба")
    _button(box, "Данные: " + ("демо JSON" if sample_mode else "сервер") + " · переключить", func() -> void:
        sample_mode = not sample_mode
        API.set_sample_enabled(sample_mode)
        count_requests = 0
        last_refresh_msec = -15000
        refresh()
        open_section("Настройки")
    , 320)
    _button(box, "Обновить", func() -> void:
        last_refresh_msec = -15000
        count_requests = 0
        refresh()
    )
    _button(box, "Вернуться ко входу", func(): get_tree().change_scene_to_file("res://main.tscn"), 220)

func _render_alerts() -> void:
    if notifications == null:
        return
    _clear(notifications)
    _label(notifications, "◉ ОПОВЕЩЕНИЯ", 18, GREEN)
    var entries := _arr(data, "alerts")
    if entries.is_empty():
        _label(notifications, "Нет новых оповещений", 14, MUTED)
    for entry in entries:
        if not entry is Dictionary:
            continue
        var alert: Dictionary = entry
        var message := str(alert.get("text", alert.get("code", "Событие"))).substr(0, 150)
        var destination := str(alert.get("section", ""))
        var cell := Vector2i(int(alert.get("x", -1)), int(alert.get("y", -1)))
        _button(notifications, message, func() -> void:
            if cell.x >= 0 and cell.y >= 0:
                open_map(cell)
            elif NAV.has(destination):
                open_section(destination)
            else:
                open_section("Обзор")
        , 170)
    if right_scroll != null and not right_scroll.visible:
        _button(notifications, "Подробнее", func(): open_section("Обзор"))

func _open_enterprise(id: String, item: Dictionary) -> void:
    current_section = "Предприятия"
    _clear(content)
    var box := _card("УПРАВЛЕНИЕ ПРЕДПРИЯТИЕМ", str(item.get("name", "Предприятие")))
    _label(box, "Показатели из /hq доступны для просмотра. Изменение настроек появится после серверного контракта.", 15, MUTED)
    var target := Vector2i(int(item.get("x", 0)), int(item.get("y", 0)))
    _button(box, "На карте", func(): open_map(target))
    _button(box, "Назад к предприятиям", func(): open_section("Предприятия"), 230)
    if not id.is_empty():
        _load_enterprise(id, box)

func _load_enterprise(id: String, host: VBoxContainer) -> void:
    if sample_mode:
        _label(host, "Демонстрационный режим: GET /enterprise отключён", 14, MUTED)
        return
    if not GameSession.is_authenticated():
        return
    var message := _label(host, "Запрос /enterprise?id=...", 14, MUTED)
    var req := HTTPRequest.new()
    req.timeout = 8.0
    add_child(req)
    req.request_completed.connect(func(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
        req.queue_free()
        if not is_instance_valid(message):
            return
        var parsed = JSON.parse_string(body.get_string_from_utf8())
        if result == HTTPRequest.RESULT_SUCCESS and code == 200 and parsed is Dictionary:
            message.text = JSON.stringify(parsed, "  ").substr(0, 6000)
        else:
            message.text = "Управление недоступно до подключения серверного API (HTTP %d)" % code
    )
    if req.request(API.ROOT + "enterprise?id=" + id.uri_encode(), API.authorize()) != OK:
        req.queue_free()

func _open_menu() -> void:
    open_section("Настройки")

func open_map(cell: Vector2i = Vector2i(-1, -1)) -> void:
    _desired_focus = cell
    map_requested.emit(cell)
    _set_active(false)
    # Scene switch, unlike a hidden Node3D, releases geometry/meshes and sync timers.
    var tree := get_tree()
    tree.set_meta("hq_focus_cell", cell)
    tree.change_scene_to_file("res://world.tscn")