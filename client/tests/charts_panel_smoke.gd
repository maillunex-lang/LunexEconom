extends SceneTree
## Headless: the price chart draws a series and a touch shows the value. No external chart library.

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
	if root.charts_panel == null:
		_fail(root, "charts panel was not wired")
		return
	var opener: Button = null
	for node in root.find_children("*", "Button", true, false):
		if node is Button and node.text == "Графики":
			opener = node
	if opener == null:
		_fail(root, "economy section has no Графики button")
		return
	opener.pressed.emit()
	await process_frame
	root._layout_ui_v1()
	var panel: Control = root.charts_panel
	if not panel.visible or panel.size.y < 180.0:
		_fail(root, "charts panel is not a full section window")
		return
	var chart: Control = null
	for node in panel.find_children("*", "", true, false):
		if node.has_method("set_points"):
			chart = node
	if chart == null:
		_fail(root, "chart control missing")
		return
	chart.custom_minimum_size = Vector2(320, 180)
	chart.size = Vector2(320, 180)
	panel.show_series([{"month": 1, "price": 100}, {"month": 2, "price": 180}, {"month": 3, "price": 140}], "price", "Мёд")
	var touch := InputEventScreenTouch.new()
	touch.pressed = true
	touch.position = Vector2(300, 40)
	chart._gui_input(touch)
	if "180" not in str(chart._tip) and "140" not in str(chart._tip) and "100" not in str(chart._tip):
		_fail(root, "touch did not show a chart value: %s" % chart._tip)
		return
	var close_btn: Button = null
	for node in panel.find_children("*", "Button", true, false):
		if node is Button and str(node.text).begins_with("Закрыть"):
			close_btn = node
	panel.hide()
	if root._hit_ui_button(close_btn.get_global_rect().get_center()) == close_btn:
		_fail(root, "hidden charts panel took a touch")
		return
	print("CHARTS_PANEL_SMOKE_PASS")
	root.queue_free()
	quit(0)
