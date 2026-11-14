extends PanelContainer
## Order book. Prices and fills come from the server; the client only chooses a product and a side.
signal close_requested

var host: Node
var _rows: VBoxContainer
var _footer: Label
var _book: Dictionary = {}
var _product := "honey"
var _side := "buy"
var pending := false


func _ready() -> void:
	name = "ExchangePanel"
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
	title.text = "Биржа"
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	title.add_theme_font_size_override("font_size", 20)
	header.add_child(title)
	header.add_child(_button("Закрыть", func(): close_requested.emit()))
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_child(scroll)
	_rows = VBoxContainer.new()
	_rows.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.add_child(_rows)
	_footer = Label.new()
	body.add_child(_footer)
	render({"product": "honey", "name": "Мёд", "bids": [], "asks": [], "orders": [], "products": []})
	hide()


func _button(text: String, callback: Callable) -> Button:
	var button := Button.new()
	button.text = text
	button.custom_minimum_size = Vector2(100, 36)
	button.mouse_filter = Control.MOUSE_FILTER_IGNORE
	button.add_theme_font_size_override("font_size", 15)
	button.pressed.connect(callback)
	return button


func bind_host(screen: Node) -> void:
	host = screen


func render(data: Dictionary) -> void:
	_book = data
	for child in _rows.get_children():
		child.queue_free()
	var products = data.get("products", [])
	if products is Array and not products.is_empty():
		var row := HBoxContainer.new()
		_rows.add_child(row)
		for item in products:
			if item is Dictionary:
				var pid := str(item.get("id", ""))
				row.add_child(_button(str(item.get("name", pid)), _choose.bind(pid)))
	var title := Label.new()
	title.text = "%s · покупка %s · продажа %s" % [str(data.get("name", _product)), _levels(data.get("bids", [])), _levels(data.get("asks", []))]
	title.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	title.add_theme_font_size_override("font_size", 16)
	_rows.add_child(title)
	_rows.add_child(_button("Купить лот по базе", _send.bind("buy")))
	_rows.add_child(_button("Продать лот по базе", _send.bind("sell")))
	var mine = data.get("orders", [])
	if mine is Array:
		for order in mine:
			if order is Dictionary and str(order.get("status", "")) == "open":
				_rows.add_child(_button("Снять %s %s" % [str(order.get("side", "")), str(order.get("qty_left", ""))], _cancel.bind(str(order.get("id", "")))))
	_footer.text = "Комиссия и коридор цены — на сервере. Самосделка запрещена."


func _levels(rows) -> String:
	if not rows is Array or rows.is_empty():
		return "—"
	var first = rows[0]
	if not first is Dictionary:
		return "—"
	return "%s×%s" % [str(first.get("qty", 0)), str(first.get("price", 0))]


func _choose(product: String) -> void:
	_product = product
	refresh()


func refresh() -> void:
	if host == null or not GameSession.is_authenticated():
		_footer.text = "Войдите, чтобы открыть биржу"
		return
	_fetch("soc/exchange/book?product=" + _product, func(book: Dictionary) -> void:
		_fetch("soc/exchange/mine", func(mine: Dictionary) -> void:
			book["orders"] = mine.get("orders", [])
			render(book)
		)
	)


func _send(side: String) -> void:
	if host == null or pending:
		return
	var price := int(_book.get("reference_price", 0))
	if price <= 0:
		_footer.text = "Нет базовой цены"
		return
	_post("soc/exchange/order", {"side": side, "product": _product, "qty": 1, "price": price})


func _cancel(order_id: String) -> void:
	_post("soc/exchange/cancel", {"order_id": order_id})


func _post(path: String, fields: Dictionary) -> void:
	if host == null or pending:
		return
	pending = true
	var payload := fields.duplicate()
	payload["request_id"] = host._new_build_request_id()
	var req := HTTPRequest.new()
	req.timeout = 12.0
	host.add_child(req)
	req.request_completed.connect(func(_r: int, code: int, _h: PackedStringArray, _b: PackedByteArray) -> void:
		req.queue_free()
		pending = false
		_footer.text = "Заявка принята" if code == 200 or code == 201 else "Биржа отказала (HTTP %d)" % code
		refresh()
	)
	var headers := PackedStringArray(["Content-Type: application/json", "Authorization: Bearer " + GameSession.access_token])
	if req.request(host.API_ROOT + path, headers, HTTPClient.METHOD_POST, JSON.stringify(payload)) != OK:
		req.queue_free()
		pending = false


func _fetch(path: String, callback: Callable) -> void:
	var req := HTTPRequest.new()
	req.timeout = 12.0
	host.add_child(req)
	req.request_completed.connect(func(result: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
		req.queue_free()
		var parsed = JSON.parse_string(body.get_string_from_utf8())
		callback.call(parsed if result == HTTPRequest.RESULT_SUCCESS and code == 200 and parsed is Dictionary else {})
	)
	var headers := PackedStringArray(["Authorization: Bearer " + GameSession.access_token])
	if req.request(host.API_ROOT + path, headers) != OK:
		req.queue_free()
		callback.call({})
