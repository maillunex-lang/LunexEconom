extends PanelContainer
## Alliance window: my alliance, directory, treasury and projects. Server decides every right.
signal close_requested

var host: Node
var _rows: VBoxContainer
var _footer: Label
var _invite_name: LineEdit
var _state: Dictionary = {}
var pending := false


func _ready() -> void:
	name = "AlliancePanel"
	mouse_filter = Control.MOUSE_FILTER_STOP
	var background := StyleBoxFlat.new()
	background.bg_color = Color(0.08, 0.17, 0.15, 0.97)
	background.border_color = Color("#567664")
	background.set_border_width_all(1)
	background.set_corner_radius_all(16)
	background.set_content_margin_all(10)
	add_theme_stylebox_override("panel", background)
	var body := VBoxContainer.new()
	body.add_theme_constant_override("separation", 6)
	add_child(body)
	var header := HBoxContainer.new()
	body.add_child(header)
	var title := Label.new()
	title.text = "Альянс"
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
	_rows.add_theme_constant_override("separation", 4)
	scroll.add_child(_rows)
	_invite_name = LineEdit.new()
	_invite_name.placeholder_text = "Имя игрока для приглашения"
	_invite_name.max_length = 24
	_invite_name.custom_minimum_size = Vector2(0, 36)
	_invite_name.mouse_filter = Control.MOUSE_FILTER_STOP
	body.add_child(_invite_name)
	_footer = Label.new()
	_footer.add_theme_font_size_override("font_size", 15)
	body.add_child(_footer)
	render({"alliance": null, "alliances": [], "invites": []})
	hide()


func _button(text: String, callback: Callable) -> Button:
	var button := Button.new()
	button.text = text
	button.custom_minimum_size = Vector2(120, 36)
	button.mouse_filter = Control.MOUSE_FILTER_IGNORE
	button.add_theme_font_size_override("font_size", 15)
	button.pressed.connect(callback)
	return button


func _line(text: String) -> void:
	var label := Label.new()
	label.text = text
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size", 16)
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_rows.add_child(label)


func bind_host(screen: Node) -> void:
	host = screen


func render(data: Dictionary) -> void:
	_state = data
	for child in _rows.get_children():
		child.queue_free()
	var alliance = data.get("alliance", null)
	if alliance is Dictionary:
		_line("«%s» · %s · участников %d" % [str(alliance.get("name", "")), str(data.get("role", "")), int(alliance.get("members", 0))])
		_line("Казна: %s ₽" % _fmt(int(alliance.get("treasury", 0))))
		var roster = alliance.get("roster", [])
		if roster is Array:
			for member in roster:
				if member is Dictionary:
					_line("• %s (%s)" % [str(member.get("name", "")), str(member.get("role", ""))])
		var projects = alliance.get("projects", [])
		if projects is Array and not projects.is_empty():
			_line("Проекты")
			for project in projects:
				if project is Dictionary:
					_line("%s %d/%d · %s" % [str(project.get("kind", "")), int(project.get("pledged", 0)), int(project.get("cost", 0)), str(project.get("status", ""))])
					if str(project.get("status", "")) == "funding" and int(project.get("remaining", 0)) > 0:
						var pid := str(project.get("id", ""))
						var amount := int(project.get("remaining", 0))
						_rows.add_child(_button("Вложить %s ₽" % _fmt(amount), _pledge.bind(pid, amount)))
					if str(data.get("role", "")) == "leader" and str(project.get("status", "")) == "funding":
						_rows.add_child(_button("Отменить проект", _post.bind("/soc/project/cancel", {"project_id": str(project.get("id", ""))})))
		if str(data.get("role", "")) == "leader":
			_rows.add_child(_button("Ферма на выбранной клетке", _project.bind("farm")))
			_rows.add_child(_button("Пригласить по имени", _invite))
			_rows.add_child(_button("Вывести 1 000 ₽", _post.bind("/soc/alliance/withdraw", {"amount": 1000})))
			_rows.add_child(_button("Распустить", _post.bind("/soc/alliance/dissolve", {})))
			var applications = data.get("applications", [])
			if applications is Array:
				for application in applications:
					if application is Dictionary and str(application.get("kind", "")) == "apply":
						_rows.add_child(_button("Принять заявку %s" % str(application.get("name", "")), _post.bind("/soc/alliance/accept", {"invite_id": str(application.get("id", ""))})))
		_rows.add_child(_button("Взнос 1 000 ₽", _post.bind("/soc/alliance/contribute", {"amount": 1000})))
		_rows.add_child(_button("Выйти", _post.bind("/soc/alliance/leave", {})))
	else:
		_line("Вы не в альянсе. Создание стоит взнос в казну.")
		_rows.add_child(_button("Создать «Север»", _post.bind("/soc/alliance/create", {"name": "Север"})))
	var invites = data.get("invites", [])
	if invites is Array:
		for invite in invites:
			if invite is Dictionary:
				_rows.add_child(_button("Принять приглашение", _post.bind("/soc/alliance/accept", {"invite_id": str(invite.get("id", ""))})))
	var directory = data.get("directory", [])
	if directory is Array and not directory.is_empty():
		_line("Альянсы")
		for item in directory:
			if item is Dictionary:
				_line("%s · %d уч." % [str(item.get("name", "")), int(item.get("members", 0))])
				_rows.add_child(_button("Заявка: %s" % str(item.get("name", "")), _post.bind("/soc/alliance/apply", {"alliance_id": str(item.get("id", ""))})))
	var ranking = data.get("ranking", [])
	if ranking is Array and not ranking.is_empty():
		_line("Рейтинг альянсов")
		for item in ranking:
			if item is Dictionary:
				_line("%d. %s · капитал %s" % [int(item.get("rank", 0)), str(item.get("name", "")), _fmt(int(item.get("capital", 0)))])
	_footer.text = "Сервер проверяет права. Скрытая панель не нажимается."


func refresh() -> void:
	if host == null:
		return
	_footer.text = "Загрузка альянса..."
	_fetch("soc/alliance", func(ok: bool, data: Dictionary) -> void:
		if not ok:
			_footer.text = "Не удалось загрузить альянс"
			return
		_fetch("soc/alliances?q=", func(ok2: bool, directory: Dictionary) -> void:
			if ok2:
				data["directory"] = directory.get("alliances", [])
			_fetch("soc/alliance-ranking?by=capital", func(ok3: bool, rank: Dictionary) -> void:
				if ok3:
					data["ranking"] = rank.get("top", [])
				render(data)
			)
		)
	)


func _fmt(amount: int) -> String:
	if host != null and host.has_method("_fmt_money"):
		return str(host._fmt_money(amount))
	return str(amount)


func _project(kind: String) -> void:
	if host == null or host.world == null:
		return
	var cell: Vector2i = host.world.selected
	if cell == Vector2i(-1, -1):
		_footer.text = "Сначала нажмите клетку на карте"
		return
	_post("/soc/project", {"kind": kind, "x": cell.x, "y": cell.y})


func _invite() -> void:
	var who := _invite_name.text.strip_edges()
	if who == "":
		_footer.text = "Введите публичное имя"
		return
	_post("/soc/alliance/invite", {"name": who})


func _pledge(project_id: String, amount: int) -> void:
	_post("/soc/project/pledge", {"project_id": project_id, "amount": amount})


func _post(path: String, fields: Dictionary) -> void:
	if host == null or pending:
		return
	var payload := fields.duplicate()
	payload["request_id"] = host._new_build_request_id()
	pending = true
	var req := HTTPRequest.new()
	req.timeout = 12.0
	host.add_child(req)
	req.request_completed.connect(func(_r: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
		req.queue_free()
		pending = false
		if code == 200 or code == 201:
			var parsed = JSON.parse_string(body.get_string_from_utf8())
			if parsed is Dictionary and parsed.has("balance"):
				host._set_balance(int(parsed["balance"]))
			refresh()
		else:
			_footer.text = "Отказ сервера (HTTP %d)" % code
	)
	var headers := PackedStringArray(["Content-Type: application/json", "Authorization: Bearer " + GameSession.access_token])
	if req.request(host.API_ROOT + path, headers, HTTPClient.METHOD_POST, JSON.stringify(payload)) != OK:
		req.queue_free()
		pending = false


func _fetch(path: String, callback: Callable) -> void:
	if host == null or not GameSession.is_authenticated():
		callback.call(false, {})
		return
	var req := HTTPRequest.new()
	req.timeout = 12.0
	host.add_child(req)
	req.request_completed.connect(func(result: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
		req.queue_free()
		var parsed = JSON.parse_string(body.get_string_from_utf8())
		callback.call(result == HTTPRequest.RESULT_SUCCESS and code == 200 and parsed is Dictionary, parsed if parsed is Dictionary else {})
	)
	var headers := PackedStringArray(["Authorization: Bearer " + GameSession.access_token])
	if req.request(host.API_ROOT + path, headers) != OK:
		req.queue_free()
		callback.call(false, {})
