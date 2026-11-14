extends SceneTree
## Headless: exchange window lists the server book and ignores touches while hidden.

func _initialize() -> void:
	call_deferred("_run")


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
	if root.exchange_panel == null or root.market_social == null:
		_fail(root, "exchange panel was not wired")
		return
	var opener: Button = null
	for node in root.find_children("*", "Button", true, false):
		if node is Button and node.text == "Биржа":
			opener = node
	if opener == null:
		_fail(root, "economy section has no Биржа button")
		return
	opener.pressed.emit()
	await process_frame
	root._layout_ui_v1()
	var panel: Control = root.exchange_panel
	if not panel.visible or panel.size.y < 180.0:
		_fail(root, "exchange panel is not a full section window")
		return
	panel.render({
		"product": "honey", "name": "Мёд", "reference_price": 200,
		"products": [{"id": "honey", "name": "Мёд"}, {"id": "oil", "name": "Нефть"}],
		"bids": [{"price": 180, "qty": 4}], "asks": [{"price": 210, "qty": 2}],
		"orders": [{"id": "abc", "side": "buy", "qty_left": 1, "status": "open"}]
	})
	await process_frame
	var text := ""
	for node in panel.find_children("*", "Label", true, false):
		text += str(node.text)
	if "Мёд" not in text or "210" not in text:
		_fail(root, "order book was not drawn")
		return
	var close_btn: Button = null
	for node in panel.find_children("*", "Button", true, false):
		if node is Button and str(node.text).begins_with("Закрыть"):
			close_btn = node
	var at: Vector2 = close_btn.get_global_rect().get_center()
	panel.hide()
	if root._hit_ui_button(at) == close_btn:
		_fail(root, "hidden exchange panel took a touch")
		return
	print("EXCHANGE_PANEL_SMOKE_PASS")
	root.queue_free()
	quit(0)
