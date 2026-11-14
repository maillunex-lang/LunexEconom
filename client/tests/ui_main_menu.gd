extends SceneTree
func _initialize() -> void: call_deferred("_run")
func _run() -> void:
    var root = load("res://world.tscn").instantiate()
    get_root().add_child(root)
    await process_frame
    await process_frame
    var nav: HBoxContainer = root.get_node("BottomNavigation")
    var section: PanelContainer = root.get_node("SectionPanel")
    assert(nav.get_child_count() == 5)
    for i in range(1,5):
        nav.get_child(i).pressed.emit()
        assert(section.visible)
        assert(not root.get_node("BuildCatalog").visible)
        assert(section.get_child(0).get_child(0).get_child(0).text == nav.get_child(i).text)
    nav.get_child(0).pressed.emit()
    assert(not section.visible and root.get_node("BuildCatalog").visible)
    print("UI_MAIN_MENU_PASS all-five-buttons/sections/close")
    root.queue_free()
    quit()