extends SceneTree
## Headless: achievement titles render without a cash reward and the hidden window takes no touch.

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
	if root.achievements_panel == null:
		_fail(root, "achievements panel was not wired")
		return
	var opener: Button = null
	for node in root.find_children("*", "Button", true, false):
		if node is Button and node.text == "Звания":
			opener = node
	if opener == null:
		_fail(root, "menu has no Звания button")
		return
	opener.pressed.emit()
	await process_frame
	root._layout_ui_v1()
	var panel: Control = root.achievements_panel
	if not panel.visible or panel.size.y < 180.0:
		_fail(root, "achievements panel is not a full section window")
		return
	panel.render({"achievements": [
		{"code": "first_building", "title": "Первое здание", "hint": "Построить", "earned": true},
		{"code": "alliance_member", "title": "В альянсе", "hint": "Состоять", "earned": false}
	]})
	await process_frame
	var text := ""
	for node in panel.find_children("*", "Label", true, false):
		text += str(node.text) + "\n"
	if "Первое здание" not in text or "₽" in text:
		_fail(root, "titles missing or a money reward was shown")
		return
	var scroll: ScrollContainer = panel.find_children("*", "ScrollContainer", true, false)[0]
	if scroll == null:
		_fail(root, "achievements body does not scroll")
		return
	var close_btn: Button = null
	for node in panel.find_children("*", "Button", true, false):
		if node is Button and str(node.text).begins_with("Закрыть"):
			close_btn = node
	panel.hide()
	if root._hit_ui_button(close_btn.get_global_rect().get_center()) == close_btn:
		_fail(root, "hidden achievements panel took a touch")
		return
	print("ACHIEVEMENTS_PANEL_SMOKE_PASS")
	root.queue_free()
	quit(0)
