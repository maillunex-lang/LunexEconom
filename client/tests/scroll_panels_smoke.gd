extends SceneTree
## Headless check: section windows fill the area between HUD and navigation, their body scrolls by touch drag,
## the header stays put, and a short tap on a button still works.

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

func _run() -> void:
	var root: Control = load("res://world.tscn").instantiate()
	get_root().add_child(root)
	await process_frame
	await process_frame
	for child in root.get_node("UIOverlay/BottomNavigation").get_children():
		if child is Button and child.text == "Экономика":
			child.pressed.emit()
	await process_frame
	var panel: Control = root.section_panel
	var nav_top: float = root.build_toolbar.position.y
	assert(panel.visible)
	assert(panel.position.y >= 60.0 and panel.position.y + panel.size.y <= nav_top, "window sits between HUD and navigation")
	assert(panel.size.y > 200.0, "window is large")
	# very long body: must scroll instead of running off the screen
	root.section_body.text = "строка\n".repeat(120)
	await process_frame
	await process_frame
	var scroll: ScrollContainer = root.section_scroll
	assert(scroll.get_v_scroll_bar().max_value > scroll.size.y, "long text needs scrolling")
	var header_y: float = root.section_title.get_global_rect().position.y
	var p := scroll.get_global_rect().get_center()
	# finger starts on text and drags up: content moves, header does not
	_touch(root, 1, p, true)
	_drag(root, 1, p + Vector2(0, -60), Vector2(0, -60))
	_drag(root, 1, p + Vector2(0, -160), Vector2(0, -100))
	_touch(root, 1, p + Vector2(0, -160), false)
	await process_frame
	assert(scroll.scroll_vertical >= 150, "drag scrolled the body: %d" % scroll.scroll_vertical)
	assert(is_equal_approx(root.section_title.get_global_rect().position.y, header_y), "header is fixed")
	# drag back down
	_touch(root, 2, p, true)
	_drag(root, 2, p + Vector2(0, 300), Vector2(0, 300))
	_touch(root, 2, p + Vector2(0, 300), false)
	assert(scroll.scroll_vertical == 0, "dragging down returns to the top")
	# short tap on the close button still works; a drag across it does not close the window
	var close_btn: Button = null
	for node in panel.find_children("*", "Button", true, false):
		if node.text.begins_with("Закрыть"):
			close_btn = node
	assert(close_btn != null)
	var c := close_btn.get_global_rect().get_center()
	_touch(root, 3, c, true)
	_drag(root, 3, c + Vector2(0, 40), Vector2(0, 40))
	_touch(root, 3, c, false)
	assert(panel.visible, "a drag that returns to the button is not a tap")
	_touch(root, 4, c, true)
	_touch(root, 4, c, false)
	assert(not panel.visible, "a short tap closes the window")
	print("SCROLL_PANELS_PASS fill/scroll/fixed-header/tap")
	root.queue_free()
	quit()
