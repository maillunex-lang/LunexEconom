extends SceneTree
func _initialize() -> void:
    call_deferred("_run")
func _run() -> void:
    var root: Control = load("res://world.tscn").instantiate()
    get_root().add_child(root)
    await process_frame
    await process_frame
    var world = root.get_node("World")
    var toolbar = root.get_node("ConstructionToolbar")
    var viewport = root.get_viewport()
    print("DEBUG viewport=", viewport.get_visible_rect(), " root=",root.get_global_rect()," toolbar=",toolbar.get_global_rect())
    for b in toolbar.get_children():
        print("DEBUG button ",b.text," rect=",b.get_global_rect()," visible=",b.is_visible_in_tree()," mouse=",b.mouse_filter)
    print("DEBUG root mouse=",root.mouse_filter," focus=",viewport.gui_get_focus_owner())
    world.selected = Vector2i(1, 1)
    var farm = toolbar.get_child(0)
    var confirm = toolbar.get_child(3)
    var p: Vector2 = farm.get_global_rect().get_center()
    var press = InputEventMouseButton.new()
    press.button_index = MOUSE_BUTTON_LEFT
    press.position = p
    press.global_position = p
    press.pressed = true
    viewport.push_input(press,true)
    await process_frame
    press = InputEventMouseButton.new()
    press.button_index = MOUSE_BUTTON_LEFT
    press.position = p
    press.global_position = p
    press.pressed = false
    viewport.push_input(press,true)
    await process_frame
    print("DEBUG hover=",viewport.gui_get_hovered_control())
    print("DEBUG after farm ",world.build_type, " selection=",world.selected," info=",root.info.text)
    p = confirm.get_global_rect().get_center()
    press = InputEventMouseButton.new()
    press.button_index = MOUSE_BUTTON_LEFT
    press.position = p
    press.global_position = p
    press.pressed = true
    viewport.push_input(press,true)
    await process_frame
    press = InputEventMouseButton.new()
    press.button_index = MOUSE_BUTTON_LEFT
    press.position = p
    press.global_position = p
    press.pressed = false
    viewport.push_input(press,true)
    await process_frame
    print("DEBUG after build ",world.building_records," selection=",world.selected," info=",root.info.text)
    root.queue_free()
    quit()
