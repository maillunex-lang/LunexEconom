extends PanelContainer
## Titles only. Achievements never pay money.
signal close_requested

var host: Node
var _rows: VBoxContainer
var _footer: Label


func _ready() -> void:
	name = "AchievementsPanel"
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
	title.text = "Достижения"
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	title.add_theme_font_size_override("font_size", 20)
	header.add_child(title)
	var close := Button.new()
	close.text = "Закрыть"
	close.custom_minimum_size = Vector2(110, 36)
	close.mouse_filter = Control.MOUSE_FILTER_IGNORE
	close.pressed.connect(func(): close_requested.emit())
	header.add_child(close)
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_child(scroll)
	_rows = VBoxContainer.new()
	_rows.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.add_child(_rows)
	_footer = Label.new()
	_footer.text = "Звания без денежных наград"
	body.add_child(_footer)
	render({"achievements": []})
	hide()


func bind_host(screen: Node) -> void:
	host = screen


func render(data: Dictionary) -> void:
	for child in _rows.get_children():
		child.queue_free()
	var items = data.get("achievements", [])
	if not items is Array or items.is_empty():
		var empty := Label.new()
		empty.text = "Список достижений появится после входа"
		_rows.add_child(empty)
		return
	for item in items:
		if not item is Dictionary:
			continue
		var label := Label.new()
		label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		label.add_theme_font_size_override("font_size", 16)
		var mark := "●" if bool(item.get("earned", false)) else "○"
		label.text = "%s %s — %s" % [mark, str(item.get("title", "")), str(item.get("hint", ""))]
		_rows.add_child(label)


func refresh() -> void:
	if host == null or not GameSession.is_authenticated():
		_footer.text = "Войдите, чтобы увидеть звания"
		return
	var req := HTTPRequest.new()
	req.timeout = 12.0
	host.add_child(req)
	req.request_completed.connect(func(result: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
		req.queue_free()
		var parsed = JSON.parse_string(body.get_string_from_utf8())
		if result == HTTPRequest.RESULT_SUCCESS and code == 200 and parsed is Dictionary:
			render(parsed)
			_footer.text = "Звания без денежных наград"
		else:
			_footer.text = "Не удалось загрузить достижения"
	)
	var headers := PackedStringArray(["Authorization: Bearer " + GameSession.access_token])
	if req.request(host.API_ROOT + "soc/achievements", headers) != OK:
		req.queue_free()
