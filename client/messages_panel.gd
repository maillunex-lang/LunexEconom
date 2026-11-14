extends PanelContainer
## Personal and alliance messages. Plain Label text only — no RichText, no HTML.
signal close_requested

var host: Node
var _rows: VBoxContainer
var _footer: Label
var _draft_box: LineEdit
var _draft := "Здравствуйте"
var _target := ""
var pending := false


func _ready() -> void:
	name = "MessagesPanel"
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
	title.text = "Сообщения"
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	title.add_theme_font_size_override("font_size", 20)
	header.add_child(title)
	header.add_child(_button("Закрыть", func(): close_requested.emit()))
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	body.add_child(scroll)
	_rows = VBoxContainer.new()
	_rows.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.add_child(_rows)
	_draft_box = LineEdit.new()
	_draft_box.placeholder_text = "Текст, без разметки"
	_draft_box.text = _draft
	_draft_box.max_length = 300
	_draft_box.custom_minimum_size = Vector2(0, 36)
	_draft_box.mouse_filter = Control.MOUSE_FILTER_STOP
	body.add_child(_draft_box)
	_footer = Label.new()
	_footer.add_theme_font_size_override("font_size", 15)
	body.add_child(_footer)
	render({"messages": []})
	hide()


func _button(text: String, callback: Callable) -> Button:
	var button := Button.new()
	button.text = text
	button.custom_minimum_size = Vector2(110, 36)
	button.mouse_filter = Control.MOUSE_FILTER_IGNORE
	button.add_theme_font_size_override("font_size", 15)
	button.pressed.connect(callback)
	return button


func bind_host(screen: Node) -> void:
	host = screen


func render(data: Dictionary) -> void:
	for child in _rows.get_children():
		child.queue_free()
	var messages = data.get("messages", [])
	if not messages is Array or messages.is_empty():
		var empty := Label.new()
		empty.text = "Пока пусто"
		_rows.add_child(empty)
	else:
		for item in messages:
			if not item is Dictionary:
				continue
			var label := Label.new()
			label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
			label.add_theme_font_size_override("font_size", 16)
			label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
			label.custom_minimum_size = Vector2(0, 28)
			# Label does not interpret markup. The server also rejects < and >.
			label.text = "%s: %s" % [str(item.get("name", "")), str(item.get("body", ""))]
			_rows.add_child(label)
			if str(item.get("name", "")) != "Система" and str(item.get("name", "")) != "":
				_target = str(item.get("name", ""))
	if _target != "":
		_rows.add_child(_button("Ответить", _send))
		_rows.add_child(_button("Заблокировать %s" % _target, _block))
	_footer.text = "Только обычный текст. Сервер режет длинные диалоги."


func refresh() -> void:
	if host == null or not GameSession.is_authenticated():
		_footer.text = "Войдите, чтобы читать сообщения"
		return
	_footer.text = "Загрузка..."
	var req := HTTPRequest.new()
	req.timeout = 12.0
	host.add_child(req)
	req.request_completed.connect(func(result: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
		req.queue_free()
		var parsed = JSON.parse_string(body.get_string_from_utf8())
		if result == HTTPRequest.RESULT_SUCCESS and code == 200 and parsed is Dictionary:
			render(parsed)
		else:
			_footer.text = "Не удалось открыть входящие"
	)
	var headers := PackedStringArray(["Authorization: Bearer " + GameSession.access_token])
	if req.request(host.API_ROOT + "soc/inbox?after=0", headers) != OK:
		req.queue_free()
		_footer.text = "Нет соединения"


func _send() -> void:
	if host == null or _target == "" or pending:
		return
	var text := _draft_box.text.strip_edges() if _draft_box != null else _draft
	if text == "":
		_footer.text = "Пустое сообщение не уйдёт"
		return
	pending = true
	var payload := {"to": _target, "body": text, "request_id": host._new_build_request_id()}
	var req := HTTPRequest.new()
	req.timeout = 12.0
	host.add_child(req)
	req.request_completed.connect(func(_r: int, code: int, _h: PackedStringArray, _b: PackedByteArray) -> void:
		req.queue_free()
		pending = false
		_footer.text = "Отправлено" if code == 200 or code == 201 else "Сервер отклонил сообщение"
		refresh()
	)
	var headers := PackedStringArray(["Content-Type: application/json", "Authorization: Bearer " + GameSession.access_token])
	if req.request(host.API_ROOT + "soc/message", headers, HTTPClient.METHOD_POST, JSON.stringify(payload)) != OK:
		req.queue_free()
		pending = false


func _block() -> void:
	if host == null or _target == "" or pending:
		return
	pending = true
	var payload := {"name": _target, "request_id": host._new_build_request_id()}
	var req := HTTPRequest.new()
	req.timeout = 12.0
	host.add_child(req)
	req.request_completed.connect(func(_r: int, _c: int, _h: PackedStringArray, _b: PackedByteArray) -> void:
		req.queue_free()
		pending = false
		_footer.text = "Игрок в чёрном списке"
	)
	var headers := PackedStringArray(["Content-Type: application/json", "Authorization: Bearer " + GameSession.access_token])
	if req.request(host.API_ROOT + "soc/block", headers, HTTPClient.METHOD_POST, JSON.stringify(payload)) != OK:
		req.queue_free()
		pending = false
