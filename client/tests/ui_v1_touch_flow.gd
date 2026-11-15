extends SceneTree
## Current UI: sector -> kind -> placement. Unauthenticated test must never
## pretend that a building was built: production construction is server-only.

var failures := 0

func _initialize() -> void:
    call_deferred("_run")

func _check(ok: bool, message: String) -> void:
    if not ok:
        failures += 1
        print("UI_TOUCH_FAIL ", message)

func _tap(point: Vector2) -> void:
    var down := InputEventScreenTouch.new()
    down.index = 0
    down.position = point
    down.pressed = true
    get_root().push_input(down, true)
    var up := InputEventScreenTouch.new()
    up.index = 0
    up.position = point
    up.pressed = false
    get_root().push_input(up, true)

func _find(node: Node, target: String) -> Node:
    if node.name == target:
        return node
    for child in node.get_children():
        var found := _find(child, target)
        if found != null:
            return found
    return null

func _run() -> void:
    get_root().get_node("GameSession").set("access_token", "")
    var root: Control = load("res://world.tscn").instantiate()
    get_root().add_child(root)
    await process_frame
    await process_frame
    var nav: Control = root.build_toolbar
    var catalog: Control = root.catalog_panel
    var card: Control = root.placement_panel
    var world: Node3D = root.world
    _tap((nav.get_child(0) as Control).get_global_rect().get_center())
    await process_frame
    _check(catalog.visible, "navigation opens catalogue")
    var sector: Button = _find(catalog, "Sector_agri") as Button
    _check(sector != null, "agriculture sector available")
    if sector != null:
        _tap(sector.get_global_rect().get_center())
        await process_frame
        _check(root.build_menu.current == "agri", "tap opened agriculture")
        var farm: Button = _find(catalog, "Kind_farm") as Button
        _check(farm != null, "farm available")
        if farm != null:
            _tap(farm.get_global_rect().get_center())
            await process_frame
            _check(card.visible and not catalog.visible and world.build_type == "farm", "farm enters placement")
    if world.build_type == "farm":
        world.selected = Vector2i(1, 1)
        _tap((card.get_child(0).get_child(1).get_child(0) as Control).get_global_rect().get_center())
        await process_frame
        _check(root.info.text.contains("Сначала войдите"), "anonymous build rejected")
        _check(world.build_type == "farm", "pending placement preserved")
    root.queue_free()
    await process_frame
    if failures == 0:
        print("UI_V1_TOUCH_FLOW_PASS navigation/sector/farm/auth-gate")
    quit(0 if failures == 0 else 1)