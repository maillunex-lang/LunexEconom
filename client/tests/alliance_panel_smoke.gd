extends SceneTree
## Headless: alliance window fills the section rect, the body scrolls, the header stays, a hidden panel takes no touch.

func _initialize() -> void:
	call_deferred("_run")


func _touch(root: Node, index: int, pos: Vector2, pressed: bool) -> void:
	var e := InputEventScreenTouch.new()
	e.index = index
	e.position = pos
	e.pressed = pressed
	root._input(e)


func _drag(root: Node, index: int, pos: Vector2, rel: Vector2) -> void:
	var e := InputEventScreenDrag.new()
	e.index = index
	e.position = pos
	e.relative = rel
	root._input(e)


func _fail(root: Node, message: String) -> void:
	push_error(message)
	if root != null:
		root.queue_free()
	quit(1)


func _run() -> void:
	var root: Control = load("res://world.tscn").instantiate()
	get_root().add_child(root)
	await process_frame
	await process_frame
	if root.alliance_panel == null:
		_fail(root, "alliance panel was not created")
		return
	var opener: Button = null
	for node in root.find_children("*", "Button", true, false):
		if node is Button and node.text == "Альянс":
			opener = node
			break
	if opener == null:
		_fail(root, "menu has no Альянс button")
		return
	opener.pressed.emit()
	await process_frame
	await process_frame
	root._layout_ui_v1()
	var panel: Control = root.alliance_panel
	if not panel.visible:
		_fail(root, "alliance panel did not open")
		return
	var nav_top: float = root.build_toolbar.position.y
	var area: Rect2 = root.panel_rect(nav_top)
	if panel.size.y < 180.0 or absf(panel.size.y - area.size.y) > 2.0:
		_fail(root, "alliance panel does not use panel_rect: %s vs %s" % [panel.size, area.size])
		return
	var roster: Array = []
	for i in 40:
		roster.append({"name": "player%d" % i, "role": "member"})
	panel.render({"alliance": {"name": "Север", "members": 40, "treasury": 50000, "roster": roster, "projects": []}, "role": "member"})
	await process_frame
	await process_frame
	var scroll: ScrollContainer = null
	var title: Label = null
	for node in panel.find_children("*", "", true, false):
		if scroll == null and node is ScrollContainer:
			scroll = node
		if title == null and node is Label and str(node.text).begins_with("Альянс"):
			title = node
	if scroll == null or title == null:
		_fail(root, "alliance window has no scroll or header")
		return
	if scroll.get_v_scroll_bar().max_value <= scroll.size.y:
		_fail(root, "long roster does not scroll")
		return
	var header_y: float = title.get_global_rect().position.y
	var p := scroll.get_global_rect().get_center()
	_touch(root, 1, p, true)
	_drag(root, 1, p + Vector2(0, -80), Vector2(0, -80))
	_drag(root, 1, p + Vector2(0, -180), Vector2(0, -100))
	_touch(root, 1, p + Vector2(0, -180), false)
	await process_frame
	if scroll.scroll_vertical < 100:
		_fail(root, "drag did not scroll the alliance body: %d" % scroll.scroll_vertical)
		return
	if not is_equal_approx(title.get_global_rect().position.y, header_y):
		_fail(root, "alliance header moved")
		return
	var close_btn: Button = null
	for node in panel.find_children("*", "Button", true, false):
		if node is Button and str(node.text).begins_with("Закрыть"):
			close_btn = node
	if close_btn == null:
		_fail(root, "no close button")
		return
	var hidden_at: Vector2 = close_btn.get_global_rect().get_center()
	panel.hide()
	var hit: Button = root._hit_ui_button(hidden_at)
	if hit != null and hit == close_btn:
		_fail(root, "hidden alliance panel still takes a touch")
		return
	panel.show()
	var c := close_btn.get_global_rect().get_center()
	_touch(root, 4, c, true)
	_touch(root, 4, c, false)
	await process_frame
	if panel.visible:
		_fail(root, "tap did not close the alliance panel")
		return
	print("ALLIANCE_PANEL_SMOKE_PASS")
	root.queue_free()
	quit(0)
