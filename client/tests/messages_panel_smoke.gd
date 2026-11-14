extends SceneTree
## Headless: messages are plain Labels, the window scrolls, a hidden panel takes no touch.

func _initialize() -> void:
	call_deferred("_run")


func _fail(root: Node, message: String) -> void:
	push_error(message)
	if root != null:
		root.queue_free()
	quit(1)


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


func _run() -> void:
	var root: Control = load("res://world.tscn").instantiate()
	get_root().add_child(root)
	await process_frame
	await process_frame
	if root.messages_panel == null:
		_fail(root, "messages panel was not created")
		return
	var opener: Button = null
	for node in root.find_children("*", "Button", true, false):
		if node is Button and node.text == "Сообщения":
			opener = node
	if opener == null:
		_fail(root, "menu has no Сообщения button")
		return
	opener.pressed.emit()
	await process_frame
	root._layout_ui_v1()
	var panel: Control = root.messages_panel
	if not panel.visible or panel.size.y < 180.0:
		_fail(root, "messages panel is not a full section window")
		return
	var messages: Array = []
	for i in 60:
		messages.append({"id": i + 1, "name": "alice", "body": "строка %d <b>не разметка</b>" % i, "channel": "dm"})
	panel.render({"messages": messages})
	await process_frame
	await process_frame
	var rich := panel.find_children("*", "RichTextLabel", true, false)
	if rich.size() != 0:
		_fail(root, "messages must not use RichTextLabel")
		return
	var saw_plain := false
	for node in panel.find_children("*", "Label", true, false):
		if "<b>" in str(node.text):
			saw_plain = true
	if not saw_plain:
		_fail(root, "message body was not shown as plain text")
		return
	var scroll: ScrollContainer = panel.find_children("*", "ScrollContainer", true, false)[0]
	if scroll.get_v_scroll_bar().max_value <= scroll.size.y:
		_fail(root, "inbox does not scroll")
		return
	var p := scroll.get_global_rect().get_center()
	_touch(root, 1, p, true)
	_drag(root, 1, p + Vector2(0, -160), Vector2(0, -160))
	_touch(root, 1, p + Vector2(0, -160), false)
	await process_frame
	if scroll.scroll_vertical < 80:
		_fail(root, "drag did not scroll messages")
		return
	var close_btn: Button = null
	for node in panel.find_children("*", "Button", true, false):
		if node is Button and str(node.text).begins_with("Закрыть"):
			close_btn = node
	var at: Vector2 = close_btn.get_global_rect().get_center()
	panel.hide()
	if root._hit_ui_button(at) == close_btn:
		_fail(root, "hidden messages panel took a touch")
		return
	print("MESSAGES_PANEL_SMOKE_PASS")
	root.queue_free()
	quit(0)
