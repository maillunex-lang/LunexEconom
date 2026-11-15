extends SceneTree
## Real scene round trip: headquarters -> 3D map focused on enterprise -> headquarters.
var failed := 0
func _initialize() -> void:
    call_deferred("_run")
func _check(ok: bool, what: String) -> void:
    if not ok:
        failed += 1
        print("FAIL ", what)
func _run() -> void:
    var hq = load("res://hq.tscn").instantiate()
    root.add_child(hq)
    hq._set_active(false)
    hq.apply_hq(load("res://hq/hq_api.gd").sample())
    await process_frame
    hq.open_map(Vector2i(40, 12))
    await process_frame
    await process_frame
    var map = current_scene
    _check(map != null and map.name == "WorldScreen", "world scene opened")
    if map != null and map.name == "WorldScreen":
        _check(map.world.focus.is_equal_approx(map.world.cell_center(Vector2i(40, 12))), "camera focus")
        _check(map.world.selected == Vector2i(40, 12), "building selected")
        var button: Button = map.get_node_or_null("UIOverlay/HUD/Top/HeadquartersButton")
        _check(button != null, "return button")
        if button != null:
            button.pressed.emit()
            await process_frame
            await process_frame
            _check(current_scene != null and current_scene.get_script().resource_path == "res://hq/hq_screen.gd", "returns to HQ")
            if current_scene != null:
                _check(not _has_world(current_scene), "3D world freed on return")
    if failed == 0:
        print("HQ_NAVIGATION_SMOKE_PASS")
    quit(0 if failed == 0 else 1)
func _has_world(n: Node) -> bool:
    if n is Node3D:
        return true
    for child in n.get_children():
        if _has_world(child):
            return true
    return false
