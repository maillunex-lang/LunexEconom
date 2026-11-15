extends SceneTree
## Current Forest Glass UI lives in UIOverlay; test layout at logical
## viewport sizes, not physical resolution under Godot's canvas scaling.

var failures := 0

func _initialize() -> void:
    call_deferred("_run")

func _check(condition: bool, message: String) -> void:
    if not condition:
        failures += 1
        print("UI_LAYOUT_FAIL ", message)

func _run() -> void:
    var root: Control = load("res://world.tscn").instantiate()
    get_root().add_child(root)
    await process_frame
    await process_frame
    for resolution in [Vector2i(1280, 720), Vector2i(960, 540), Vector2i(846, 388), Vector2i(2340, 1080)]:
        get_root().size = resolution
        await process_frame
        await process_frame
        root._layout_ui_v1()
        var logical_size: Vector2 = root.get_viewport_rect().size
        var nav: Control = root.build_toolbar
        _check(nav != null and nav.get_global_rect().position.y > 0, "navigation present " + str(resolution))
        for panel in [root.catalog_panel, root.placement_panel, root.details_panel]:
            var rect: Rect2 = panel.get_global_rect()
            _check(rect.position.x >= 0 and rect.end.x <= logical_size.x + 2, panel.name + " horizontal " + str(resolution) + " " + str(rect))
            _check(rect.position.y >= 0 and rect.end.y <= logical_size.y + 2, panel.name + " vertical " + str(resolution) + " " + str(rect))
        print("UI_LAYOUT_PASS ", resolution, " logical=", logical_size)
    root.queue_free()
    await process_frame
    quit(0 if failures == 0 else 1)