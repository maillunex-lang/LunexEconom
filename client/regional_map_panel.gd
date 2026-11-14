extends PanelContainer
## Cacheable, read-only geographic overview of twenty game regions.
signal city_selected(city)

var host: Control
var cities: Array = []
var regions: Array = []
var routes: Array = []
var highway_cells: Dictionary = {}
var loaded := false
var loading := false
var current_city: Dictionary = {}
var pan := Vector2.ZERO
var map_zoom := 1.0
var fingers: Dictionary = {}
var touch_start := Vector2.ZERO
var touch_moved := false
var _pinch_start := 0.0
var map_canvas: Control
var body_scroll: ScrollContainer
var details: Label
var visit_button: Button
var economy_view: Dictionary = {}     # GET /economy/regions: city economies, prices and shipments
const CACHE_FILE := "user://lunexeconom_geo_regions_v1.json"

func setup(parent: Control) -> void:
    host = parent
    name = "RegionalMapPanel"
    add_theme_stylebox_override("panel", host._style())
    mouse_filter = Control.MOUSE_FILTER_STOP
    host.get_node("UIOverlay").add_child(self)
    var frame := VBoxContainer.new()
    add_child(frame)
    var header := HBoxContainer.new()
    frame.add_child(header)
    var label := Label.new()
    label.text = "Карта Башкортостана · игровые регионы"
    label.add_theme_font_size_override("font_size", 20)
    label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    header.add_child(label)
    header.add_child(host._ui_button("Закрыть ×", close_panel, 130))
    map_canvas = load("res://regional_map_canvas.gd").new()
    map_canvas.name = "RegionalMapCanvas"
    map_canvas.owner_panel = self
    map_canvas.size_flags_vertical = Control.SIZE_EXPAND_FILL
    map_canvas.custom_minimum_size = Vector2(0, 140)
    frame.add_child(map_canvas)
    body_scroll = ScrollContainer.new()
    body_scroll.custom_minimum_size = Vector2(0, 85)
    body_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
    body_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
    frame.add_child(body_scroll)
    var text_column := VBoxContainer.new()
    body_scroll.add_child(text_column)
    details = Label.new()
    details.add_theme_font_size_override("font_size", 15)
    details.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    details.text = "Загружаем города и трассы..."
    text_column.add_child(details)
    visit_button = host._ui_button("Перейти к городу", _jump, 240)
    text_column.add_child(visit_button)
    visit_button.hide()
    hide()
    host.get_viewport().size_changed.connect(_place)
    _restore_cache()

func _place() -> void:
    if host == null or not is_inside_tree():
        return
    var rect: Rect2 = host.panel_rect(host.build_toolbar.position.y)
    # Fit short landscape screens, including 846×388 and Android safe areas.
    map_canvas.custom_minimum_size = Vector2(0, maxf(65.0, rect.size.y - 150.0))
    body_scroll.custom_minimum_size = Vector2(0, 35.0)
    custom_minimum_size = rect.size
    size = rect.size
    position = rect.position

func close_panel() -> void:
    hide()
    host._open_section("Меню")

func open_panel() -> void:
    for panel in [host.section_panel, host.catalog_panel, host.placement_panel,
                  host.details_panel, host.leaderboard_panel, host.feed_panel, host.contracts_panel]:
        if panel != null:
            panel.hide()
    show()
    _place()
    _load_economy()
    if loaded:
        details.text = "Нажмите на город. Один палец: двигайте карту, два: изменяйте масштаб."
        if not current_city.is_empty():
            _show_details()
        return
    if loading:
        return
    loading = true
    details.text = "Загружаем карту регионов..."
    host._api_get("geo/cities", false, func(data: Dictionary) -> void:
        if not data.get("cities", null) is Array:
            _fail()
            return
        var city_list: Array = data["cities"]
        host._api_get("geo/regions", false, func(region_data: Dictionary) -> void:
            if not region_data.get("regions", null) is Array:
                _fail()
                return
            host._api_get("geo/routes", false, func(route_data: Dictionary) -> void:
                if not route_data.get("routes", null) is Array:
                    _fail()
                    return
                set_geo_data(city_list, region_data["regions"], route_data["routes"])
                _persist_cache()
            )
        )
    )

func _load_economy() -> void:
    if host == null or not host.has_method("_api_get"):
        return
    host._api_get("economy/regions", false, func(data: Dictionary) -> void:
        if data.get("cities", null) is Array:
            economy_view = data
            if loaded and not current_city.is_empty() and visible:
                _show_details()
    )

## Economy lines of one city: residents, wage, local prices and goods on the road (delivery time grows with the road distance).
func economy_lines(city_id: String) -> PackedStringArray:
    var lines := PackedStringArray()
    var entry: Dictionary = {}
    for item in economy_view.get("cities", []):
        if item is Dictionary and str(item.get("id", "")) == city_id:
            entry = item
    if entry.is_empty():
        if not economy_view.is_empty():
            lines.append("Экономика города пока не запущена: она включается, когда в городе появляется ваше здание.")
        return lines
    lines.append("Экономика: жителей %d, рабочих мест %d, зарплата %d ₽, укомплектованность %d%%." % [
        int(entry.get("population", 0)), int(entry.get("jobs", 0)), int(entry.get("wage", 0)), roundi(float(entry.get("staffing", 1.0)) * 100.0)])
    var prices: Dictionary = entry.get("prices", {})
    var parts := PackedStringArray()
    for product in ["honey", "oil", "goods"]:
        var row = prices.get(product, null)
        if row is Dictionary:
            parts.append("%s %d ₽" % [{"honey": "мёд", "oil": "нефть", "goods": "товары"}[product], int(row.get("price", 0))])
    if not parts.is_empty():
        lines.append("Цены здесь: " + ", ".join(parts))
    for lane in economy_view.get("lanes", []):
        if lane is Dictionary and str(lane.get("from", "")) == city_id and str(lane.get("to", "")) == "ufa":
            lines.append("До Уфы: %d км по дорогам, в пути около %d ч." % [int(lane.get("road_km", 0)), int(lane.get("hours", 0))])
    var sent := 0
    for shipment in economy_view.get("recent", []):
        if shipment is Dictionary and str(shipment.get("origin", "")) == city_id:
            sent += int(shipment.get("qty", 0))
    if sent:
        lines.append("В этом месяце отправлено отсюда: %d ед." % sent)
    return lines

func _fail() -> void:
    loading = false
    details.text = "Не удалось загрузить карту. Проверьте сеть и откройте карту снова."
    visit_button.hide()

func set_geo_data(new_cities: Array, new_regions: Array, new_routes: Array) -> void:
    if new_cities.size() != 20 or new_regions.size() != 20:
        _fail()
        return
    cities = new_cities.duplicate(true)
    regions = new_regions.duplicate(true)
    routes = new_routes.duplicate(true)
    highway_cells.clear()
    for route in routes:
        if not route is Dictionary:
            continue
        for point in route.get("cells", []):
            if point is Array and point.size() == 2:
                highway_cells[Vector2i(int(point[0]), int(point[1]))] = true
    loaded = true
    loading = false
    if details != null:
        details.text = "Выберите город на карте · перетаскивайте и масштабируйте двумя пальцами."
    _select_ufa()
    if map_canvas != null:
        map_canvas.queue_redraw()
    if host != null and host.world != null:
        for chunk in host.world.active_chunks.values():
            chunk.queue_redraw()

func _restore_cache() -> void:
    if not FileAccess.file_exists(CACHE_FILE):
        return
    var file := FileAccess.open(CACHE_FILE, FileAccess.READ)
    if file == null:
        return
    var parsed = JSON.parse_string(file.get_as_text())
    file.close()
    if parsed is Dictionary and parsed.get("cities", null) is Array and parsed.get("regions", null) is Array and parsed.get("routes", null) is Array:
        set_geo_data(parsed["cities"], parsed["regions"], parsed["routes"])

func _persist_cache() -> void:
    var file := FileAccess.open(CACHE_FILE, FileAccess.WRITE)
    if file == null:
        return
    file.store_string(JSON.stringify({"cities": cities, "regions": regions, "routes": routes}))
    if file.get_error() != OK:
        push_warning("Geographic cache could not be written")
    file.close()

func _select_ufa() -> void:
    for city in cities:
        if city is Dictionary and str(city.get("id", "")) == "ufa":
            current_city = city
            _show_details()
            return

func _show_details() -> void:
    if current_city.is_empty():
        return
    var city_id := str(current_city.get("id", ""))
    var title := str(current_city.get("name", "?"))
    var center := Vector2i(int(current_city.get("x", 0)), int(current_city.get("y", 0)))
    var buildings := 0
    if host != null and host.world != null:
        for key in host.world.server_cells.keys():
            if (key as Vector2i).distance_to(center) <= int(current_city.get("radius", 15)):
                if str(host.world.server_cells[key].get("owner", "")) == GameSession.username:
                    buildings += 1
    var source: Dictionary = current_city
    var estimated_population := int(source.get("population_estimate", 0))
    if host != null and host.has_method("geo_month_index"):
        var month_index: int = maxi(host.geo_month_index(), 0)
        var drift: float = float(source.get("monthly_growth_permille", 0.0)) / 1000.0
        estimated_population = roundi(float(estimated_population) * clampf(1.0 + float(month_index) * drift, 0.8, 1.2))
    var ufa: Dictionary = {}
    for city in cities:
        if city is Dictionary and str(city.get("id", "")) == "ufa":
            ufa = city
            break
    var approximate_km := 0.0
    if not ufa.is_empty():
        approximate_km = Vector2(
            float(current_city.get("x", 0)) - float(ufa.get("x", 0)),
            float(current_city.get("y", 0)) - float(ufa.get("y", 0))
        ).length() / 3.0
    var lines := PackedStringArray([
        "%s · %s" % [title, str(source.get("region", ""))],
        "Население: примерно %d (оценка). Специализация: %s." % [
            estimated_population, str(source.get("specialization", ""))],
        "От Уфы: около %d км по прямой. Ваши здания в загруженной области: %d." % [roundi(approximate_km), buildings]
    ])
    lines.append_array(economy_lines(city_id))
    details.text = "\n".join(lines)
    visit_button.show()
    city_selected.emit(source)

func _jump() -> void:
    if current_city.is_empty():
        return
    host.goto_geo_city(current_city)
    hide()

func project(city: Dictionary) -> Vector2:
    var x := float(city.get("x", 0))
    var y := float(city.get("y", 0))
    var area := map_canvas.size if map_canvas != null else Vector2(500, 280)
    # Separate map coordinates, not the in-game isometric projection.
    return area * 0.5 + pan + Vector2(x, y) * (0.12 * map_zoom)

func draw_map(canvas: Control) -> void:
    var area: Vector2 = canvas.size
    canvas.draw_rect(Rect2(Vector2.ZERO, area), Color("#172e32"))
    if not loaded:
        return
    for region in regions:
        if not region is Dictionary:
            continue
        var id := str(region.get("center_city_id", ""))
        for city in cities:
            if city is Dictionary and str(city.get("id", "")) == id:
                canvas.draw_circle(project(city), maxf(15.0, 37.0 * map_zoom), Color(0.27, 0.43, 0.35, 0.13))
                break
    for route in routes:
        if not route is Dictionary:
            continue
        var a: Dictionary = {}
        var b: Dictionary = {}
        for city in cities:
            if str(city.get("id", "")) == str(route.get("from", "")):
                a = city
            if str(city.get("id", "")) == str(route.get("to", "")):
                b = city
        if a.is_empty() or b.is_empty():
            continue
        canvas.draw_line(project(a), project(b), Color("#b8a86b"), maxf(1.5, 2.5 * map_zoom), true)
    for city in cities:
        if not city is Dictionary:
            continue
        var p := project(city)
        var pop: int = int(city.get("population_estimate", 0))
        var diameter := clampf(3.0 + sqrt(float(pop) / 7000.0), 4.0, 17.0)
        var selected := str(current_city.get("id", "")) == str(city.get("id", ""))
        canvas.draw_circle(p, diameter, Color("#efca79") if selected else Color("#a7d6ba"))
        canvas.draw_string(ThemeDB.fallback_font, p + Vector2(diameter + 3, 4), str(city.get("name", "")),
            HORIZONTAL_ALIGNMENT_LEFT, -1, 12, Color("#eff8ed"))

func select_at(pos: Vector2) -> void:
    var nearest: Dictionary = {}
    var distance := 28.0
    for city in cities:
        if city is Dictionary:
            var d: float = project(city).distance_to(pos)
            if d < distance:
                distance = d
                nearest = city
    if not nearest.is_empty():
        current_city = nearest
        _show_details()
        map_canvas.queue_redraw()

func map_input(event: InputEvent) -> void:
    if event is InputEventScreenTouch:
        if event.pressed:
            fingers[event.index] = event.position
            if fingers.size() == 1:
                touch_start = event.position
                touch_moved = false
            elif fingers.size() == 2:
                var positions := fingers.values()
                _pinch_start = positions[0].distance_to(positions[1])
                touch_moved = true
        else:
            if fingers.size() == 1 and not touch_moved:
                select_at(event.position - map_canvas.global_position)
            fingers.erase(event.index)
            _pinch_start = 0.0
    elif event is InputEventScreenDrag and fingers.has(event.index):
        var previous: Vector2 = fingers[event.index]
        fingers[event.index] = event.position
        if fingers.size() == 1:
            pan += event.position - previous
            touch_moved = true
        elif fingers.size() == 2:
            var pts := fingers.values()
            var distance: float = pts[0].distance_to(pts[1])
            if _pinch_start > 0:
                map_zoom = clampf(map_zoom * distance / _pinch_start, 0.35, 5.0)
            _pinch_start = distance
            touch_moved = true
        map_canvas.queue_redraw()
    elif event is InputEventMouseButton:
        if event.button_index == MOUSE_BUTTON_WHEEL_UP and event.pressed:
            map_zoom = minf(map_zoom * 1.18, 5.0)
        elif event.button_index == MOUSE_BUTTON_WHEEL_DOWN and event.pressed:
            map_zoom = maxf(map_zoom / 1.18, 0.35)
        elif event.button_index == MOUSE_BUTTON_LEFT and event.pressed:
            touch_start = event.position
            touch_moved = false
        elif event.button_index == MOUSE_BUTTON_LEFT and not event.pressed and not touch_moved:
            select_at(event.position)
        map_canvas.queue_redraw()
    elif event is InputEventMouseMotion and event.button_mask & MOUSE_BUTTON_MASK_LEFT:
        pan += event.relative
        touch_moved = true
        map_canvas.queue_redraw()
