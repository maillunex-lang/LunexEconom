extends SceneTree
func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    var scene: PackedScene = load("res://world.tscn")
    var root: Control = scene.instantiate()
    get_root().add_child(root)
    await process_frame
    await process_frame
    var world = root.get_node("World")
    var bar: Control = root.get_node("ConstructionToolbar")
    var rect: Rect2 = bar.get_global_rect()
    var viewport: Vector2 = root.get_viewport_rect().size
    assert(rect.position.y > viewport.y * 0.6, "toolbar must be in bottom 40 percent")
    assert(rect.end.y <= viewport.y, "toolbar must fit viewport")
    var button: Control = bar.get_child(0)
    var point: Vector2 = button.get_global_rect().get_center()
    assert(root.is_world_ui_point(point), "toolbar touch must be blocked")
    world.selected = Vector2i(1, 1)
    world.choose_build("farm")
    var touch_down := InputEventScreenTouch.new()
    touch_down.index = 0
    touch_down.position = point
    touch_down.pressed = true
    world._input(touch_down)
    var touch_up := InputEventScreenTouch.new()
    touch_up.index = 0
    touch_up.position = point
    touch_up.pressed = false
    world._input(touch_up)
    assert(world.selected == Vector2i(1, 1), "UI tap must not change selection")
    assert(world.place_building().get("ok", false), "construction should succeed after UI tap")
    print("WORLD_027_TOUCH_FIX_PASS toolbar_bottom/ui_touch/selection/build")
    root.queue_free()
    quit()
