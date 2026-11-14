extends SceneTree
func _initialize() -> void: call_deferred("_run")
func _run() -> void:
    var root = load("res://world.tscn").instantiate()
    get_root().add_child(root)
    for resolution in [Vector2i(1280,720),Vector2i(960,540),Vector2i(846,388),Vector2i(2340,1080)]:
        get_root().size = resolution
        await process_frame
        await process_frame
        var nav: Control = root.get_node("BottomNavigation")
        var catalog: Control = root.get_node("BuildCatalog")
        var placement: Control = root.get_node("PlacementCard")
        var details: Control = root.get_node("EnterpriseDetails")
        root._layout_ui_v1(Vector2(resolution))
        assert(nav.get_global_rect().position.y >= 0)
        for panel in [catalog,placement,details]:
            print("PANEL ",resolution," ",panel.name," pos=",panel.position," size=",panel.size)
            assert(panel.position.x >= 0 and panel.position.x + panel.size.x <= resolution.x + 2)
            assert(panel.position.y >= 0 and panel.position.y + panel.size.y <= resolution.y + 2)
        print("UI_LAYOUT_PASS ",resolution)
    root.queue_free()
    quit()