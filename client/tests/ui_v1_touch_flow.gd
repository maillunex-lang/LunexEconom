extends SceneTree
func _initialize() -> void: call_deferred("_run")
func _tap(point: Vector2) -> void:
    var d := InputEventScreenTouch.new()
    d.index = 0
    d.position = point
    d.pressed = true
    get_root().push_input(d,true)
    var u := InputEventScreenTouch.new()
    u.index = 0
    u.position = point
    u.pressed = false
    get_root().push_input(u,true)
func _run() -> void:
    var root = load("res://world.tscn").instantiate()
    get_root().add_child(root)
    await process_frame
    await process_frame
    var nav = root.get_node("BottomNavigation")
    var catalog = root.get_node("BuildCatalog")
    var card = root.get_node("PlacementCard")
    var world = root.get_node("World")
    _tap(nav.get_child(0).get_global_rect().get_center())
    assert(catalog.visible)
    await process_frame
    _tap(catalog.get_child(0).get_child(1).get_child(0).get_global_rect().get_center())
    assert(card.visible and not catalog.visible and world.build_type == "farm")
    await process_frame
    var found := false
    for y in range(1,18):
        var c := Vector2i(1,y)
        if world.preview_build(c).get("ok",false):
            world.selected = c
            found = true
            break
    assert(found)
    var cell: Vector2i = world.selected
    _tap(card.get_child(0).get_child(1).get_child(0).get_global_rect().get_center())
    assert(world.building_at(cell) == "farm")
    assert(not card.visible and world.build_type.is_empty())
    print("UI_V1_TOUCH_FLOW_PASS catalog/tile/confirm/visible-building/clear")
    root.queue_free()
    quit()