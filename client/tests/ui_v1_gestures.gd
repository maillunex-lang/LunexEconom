extends SceneTree
func _initialize() -> void: call_deferred("_run")
func _run() -> void:
    var root = load("res://world.tscn").instantiate()
    get_root().add_child(root)
    await process_frame
    await process_frame
    var world = root.get_node("World")
    var nav = root.get_node("BottomNavigation")
    var catalog = root.get_node("BuildCatalog")
    var button_pos: Vector2 = nav.get_child(0).get_global_rect().get_center()
    var selected_before: Vector2i = world.selected
    var down := InputEventScreenTouch.new()
    down.index = 0
    down.pressed = true
    down.position = button_pos
    get_root().push_input(down,true)
    var up := InputEventScreenTouch.new()
    up.index = 0
    up.pressed = false
    up.position = button_pos
    get_root().push_input(up,true)
    assert(catalog.visible)
    assert(world.selected == selected_before)
    catalog.hide()
    var a := InputEventScreenTouch.new()
    a.index = 0
    a.pressed = true
    a.position = Vector2(480,280)
    get_root().push_input(a,true)
    var b := InputEventScreenTouch.new()
    b.index = 1
    b.pressed = true
    b.position = Vector2(620,280)
    get_root().push_input(b,true)
    var drag := InputEventScreenDrag.new()
    drag.index = 1
    drag.position = Vector2(680,280)
    drag.relative = Vector2(60,0)
    get_root().push_input(drag,true)
    assert(world.target_zoom > 0)
    b.pressed = false
    b.position = drag.position
    get_root().push_input(b,true)
    a.pressed = false
    get_root().push_input(a,true)
    print("UI_V1_GESTURES_PASS ui-isolation/two-touch/no-crash")
    root.queue_free()
    quit()