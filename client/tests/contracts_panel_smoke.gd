extends SceneTree
## Headless check: the contract board stays hidden until Economy is opened,
## and buttons on a hidden panel do not receive touches.

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	var root: Control = load("res://world.tscn").instantiate()
	get_root().add_child(root)
	await process_frame
	await process_frame
	var panel: Control = root.get_node("UIOverlay/ContractsPanel")
	var shortcut: Control = root.contract_shortcut
	assert(panel != null and shortcut != null)
	assert(not panel.visible, "contract panel starts hidden")
	assert(not shortcut.visible, "contract shortcut starts hidden")
	assert(root._hit_ui_button(panel.get_global_rect().get_center()) == null, "hidden panel must not take touches")
	for child in root.get_node("UIOverlay/BottomNavigation").get_children():
		if child is Button and child.text == "Экономика":
			child.pressed.emit()
	await process_frame
	assert(shortcut.visible and shortcut.is_visible_in_tree(), "shortcut only with Economy")
	assert(not panel.visible)
	var open_btn: Button = null
	for child in shortcut.get_children():
		if child is Button and child.text == "Контракты":
			open_btn = child
	assert(open_btn != null and open_btn.is_visible_in_tree())
	var open_point := open_btn.get_global_rect().get_center()
	assert(root._hit_ui_button(open_point) == open_btn)
	open_btn.pressed.emit()
	await process_frame
	assert(panel.visible and panel.is_visible_in_tree())
	assert(not shortcut.is_visible_in_tree(), "shortcut hides while the board is open")
	var close_btn: Button = null
	for node in panel.find_children("*", "Button", true, false):
		if node.text == "Закрыть":
			close_btn = node
	assert(close_btn != null and close_btn.is_visible_in_tree())
	assert(root._hit_ui_button(close_btn.get_global_rect().get_center()) == close_btn)
	close_btn.pressed.emit()
	await process_frame
	assert(not panel.visible and not panel.is_visible_in_tree())
	assert(root._hit_ui_button(close_btn.get_global_rect().get_center()) != close_btn, "closed board must ignore touches (the Economy window now sits under the same spot)")
	assert(shortcut.visible)
	for child in root.get_node("UIOverlay/BottomNavigation").get_children():
		if child is Button and child.text == "Город":
			child.pressed.emit()
	await process_frame
	assert(not shortcut.visible and not panel.visible)
	print("CONTRACTS_PANEL_PASS hidden/economy-only/open/close/touch")
	root.queue_free()
	quit()
