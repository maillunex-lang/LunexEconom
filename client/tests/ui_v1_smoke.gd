extends SceneTree
func _initialize() -> void:
    call_deferred("_run")
func _run() -> void:
    var root = load("res://world.tscn").instantiate()
    get_root().add_child(root)
    await process_frame
    await process_frame
    var world = root.get_node("World")
    var nav = root.get_node("BottomNavigation")
    var catalog = root.get_node("BuildCatalog")
    var card = root.get_node("PlacementCard")
    assert(nav.get_child_count() == 5)
    nav.get_child(0).pressed.emit()
    assert(catalog.visible and not card.visible)
    var tile = catalog.get_child(0).get_child(1).get_child(0)
    tile.pressed.emit()
    assert(world.build_type == "farm" and card.visible and not catalog.visible)
    var cell := Vector2i(1,1)
    world.selected = cell
    if not world.preview_build(cell).get("ok",false):
        for y in range(1,18):
            if world.preview_build(Vector2i(1,y)).get("ok",false):
                cell = Vector2i(1,y)
                world.selected = cell
                break
    assert(world.preview_build(cell).get("ok",false))
    card.get_child(0).get_child(1).get_child(0).pressed.emit()
    assert(world.building_at(cell) == "farm")
    assert(world.build_type.is_empty() and not card.visible)
    assert(world.cell_kind(cell.x,cell.y) == 6)
    print("UI_V1_SMOKE_PASS navigation/catalog/placement/building/clear-preview")
    root.queue_free()
    quit()