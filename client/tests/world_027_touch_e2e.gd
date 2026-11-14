extends SceneTree
func _initialize() -> void:
    call_deferred("_run")
func _tap(root: Control, point: Vector2) -> void:
    var down := InputEventScreenTouch.new()
    down.index = 0
    down.position = point
    down.pressed = true
    root._input(down)
    var up := InputEventScreenTouch.new()
    up.index = 0
    up.position = point
    up.pressed = false
    root._input(up)
func _run() -> void:
    var root: Control = load("res://world.tscn").instantiate()
    get_root().add_child(root)
    await process_frame
    await process_frame
    var world = root.get_node("World")
    var bar = root.get_node("ConstructionToolbar")
    assert(bar.get_global_rect().position.y > root.get_viewport_rect().size.y * 0.6)
    var cases = [
        {"index":0,"kind":"farm","cell":Vector2i(1,1)},
        {"index":1,"kind":"mine","cell":Vector2i(1,4)},
        {"index":2,"kind":"factory","cell":Vector2i(1,8)}
    ]
    for case in cases:
        var kind: String = case["kind"]
        var cell: Vector2i = case["cell"]
        world.selected = cell
        _tap(root, bar.get_child(case["index"]).get_global_rect().get_center())
        assert(world.build_type == kind, "touch did not choose " + kind)
        assert(world.preview_build(cell).get("ok",false), "site not buildable " + kind)
        _tap(root, bar.get_child(3).get_global_rect().get_center())
        assert(world.building_at(cell) == kind, "touch did not place " + kind)
        assert(world.cell_kind(cell.x,cell.y) == 6, "building not rendered " + kind)
        assert(world.planner.occupied.has(cell), "not reserved " + kind)
    print("WORLD_027_TOUCH_E2E_PASS farm/mine/factory/button-taps/rendered-kind")
    root.queue_free()
    quit()
