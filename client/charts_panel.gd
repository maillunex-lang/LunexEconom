extends PanelContainer
## Price and city charts. The line is drawn locally; numbers are the server's history.
signal close_requested

var host: Node
var _chart: Control
var _footer: Label
var _products: HBoxContainer
var _product := "honey"
var _months := "12"
var _mode := "price"
var _products_ready := false


func _ready() -> void:
	name = "ChartsPanel"
	mouse_filter = Control.MOUSE_FILTER_STOP
	var background := StyleBoxFlat.new()
	background.bg_color = Color(0.08, 0.17, 0.15, 0.97)
	background.border_color = Color("#567664")
	background.set_border_width_all(1)
	background.set_corner_radius_all(16)
	background.set_content_margin_all(10)
	add_theme_stylebox_override("panel", background)
	var body := VBoxContainer.new()
	add_child(body)
	var header := HBoxContainer.new()
	body.add_child(header)
	var title := Label.new()
	title.text = "Графики"
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	title.add_theme_font_size_override("font_size", 20)
	header.add_child(title)
	header.add_child(_button("Закрыть", func(): close_requested.emit()))
	_products = HBoxContainer.new()
	body.add_child(_products)
	var periods := HBoxContainer.new()
	body.add_child(periods)
	periods.add_child(_button("12", func(): _set_months("12")))
	periods.add_child(_button("24", func(): _set_months("24")))
	periods.add_child(_button("Все", func(): _set_months("all")))
	periods.add_child(_button("Город", func(): _set_mode("economy")))
	_chart = load("res://price_chart.gd").new()
	_chart.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_child(_chart)
	_footer = Label.new()
	_footer.text = "Касание графика показывает значение"
	body.add_child(_footer)
	hide()


func _button(text: String, callback: Callable) -> Button:
	var button := Button.new()
	button.text = text
	button.custom_minimum_size = Vector2(72, 36)
	button.mouse_filter = Control.MOUSE_FILTER_IGNORE
	button.add_theme_font_size_override("font_size", 15)
	button.pressed.connect(callback)
	return button


func bind_host(screen: Node) -> void:
	host = screen


func show_series(points: Array, key: String, caption: String) -> void:
	_chart.set_points(points, key)
	_footer.text = caption


func _fill_products(items) -> void:
	if _products_ready or not items is Array or items.is_empty():
		return
	for item in items:
		if item is Dictionary:
			var pid := str(item.get("id", ""))
			_products.add_child(_button(str(item.get("name", pid)), _set_product.bind(pid)))
	_products_ready = true


func _set_product(product: String) -> void:
	_product = product
	_mode = "price"
	refresh()


func _set_mode(mode: String) -> void:
	_mode = mode
	refresh()


func _set_months(months: String) -> void:
	_months = months
	refresh()


func refresh() -> void:
	if host == null or not GameSession.is_authenticated():
		_footer.text = "Войдите, чтобы увидеть графики"
		return
	var path := "soc/charts/economy?months=" + _months if _mode == "economy" else "soc/charts/prices?product=%s&months=%s" % [_product, _months]
	var req := HTTPRequest.new()
	req.timeout = 12.0
	host.add_child(req)
	req.request_completed.connect(func(result: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
		req.queue_free()
		var parsed = JSON.parse_string(body.get_string_from_utf8())
		if result != HTTPRequest.RESULT_SUCCESS or code != 200 or not parsed is Dictionary:
			_footer.text = "График не загрузился"
			return
		var points: Array = parsed.get("points", [])
		_fill_products(parsed.get("products", []))
		if _mode == "economy":
			show_series(points, "population", "Население")
		else:
			show_series(points, "price", str(parsed.get("name", _product)))
	)
	var headers := PackedStringArray(["Authorization: Bearer " + GameSession.access_token])
	if req.request(host.API_ROOT + path, headers) != OK:
		req.queue_free()
