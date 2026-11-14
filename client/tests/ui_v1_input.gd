extends SceneTree
func _initialize() -> void: call_deferred("_run")
func _tap(point: Vector2) -> void:
    var down := InputEventScreenTouch.new()
    down.position = point
    down.pressed = true
    get_root().push_input(down, true)
    var up := InputEventScreenTouch.new()
    up.position = point
    up.pressed = false
    get_root().push_input(up, true)
func _run() -> void:
    var root = load("res://world.tscn").instantiate()
    get_root().add_child(root)
    await process_frame
    await process_frame
    await process_frame
    var nav = root.get_node("BottomNavigation")
    var catalog = root.get_node("BuildCatalog")
    _tap(nav.get_child(0).get_global_rect().get_center())
    await process_frame
    print("UI_INPUT_CATALOG_VISIBLE ",catalog.visible)
    if not catalog.visible:
        print("UI_INPUT_TOUCH_FAIL")
    else:
        print("UI_INPUT_TOUCH_PASS")
    root.queue_free()
    quit()