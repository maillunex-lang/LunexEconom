extends SceneTree
const SIZES := [Vector2i(1280,720),Vector2i(2400,1080),Vector2i(2000,1200),Vector2i(1920,1080),Vector2i(2560,1080)]
const Mock = preload("res://tests/chain2_mock.gd")
const Adapter = preload("res://world/api.gd")
func _initialize() -> void:
    call_deferred("_run")
func _run() -> void:
    var index: int = int(OS.get_environment("LUNEX_TEST_SIZE_INDEX"))
    assert(index >= 0 and index < SIZES.size())
    var bounds: Vector2i = SIZES[index]
    DisplayServer.window_set_size(bounds)
    root.content_scale_mode = Window.CONTENT_SCALE_MODE_DISABLED
    root.content_scale_size = bounds
    root.size = bounds
    var app: Control = load("res://main.tscn").instantiate()
    root.add_child(app)
    for i in range(5):
        await process_frame
    app._show_headquarters()
    app._on_viewport_resized()
    await process_frame
    assert(app.headquarters_screen.wallet != null)
    assert(app.headquarters_screen.calendar != null)
    assert(app.headquarters_screen._layout._wide == (bounds.x >= 1600))
    assert(app.headquarters_screen._layout.list_area.visible)
    _check_targets(app.headquarters_screen)
    _shot("ui2_hq",bounds)
    app.router.go("map")
    await process_frame
    assert(app.map_screen._zoom_tools != null)
    assert(app.map_screen.panel.offset_right <= 0)
    _check_targets(app.map_screen._zoom_tools)
    _shot("ui2_map_panels",bounds)
    app.router.go("build")
    var mock := Mock.new()
    root.add_child(mock)
    var adapter := Adapter.new()
    root.add_child(adapter)
    adapter.mock = Callable(mock,"respond")
    app.build_screen.catalog.configure(adapter)
    app.build_screen.service.configure(adapter)
    app.build_screen.zone = "free"
    app.build_screen.wallet_balance = 999999
    await app.build_screen._load()
    await process_frame
    assert(app.build_screen.rows.get_child_count() == 42)
    app.build_screen.resize_ui(bounds)
    assert(app.build_screen._columns._wide == (bounds.x >= 1600))
    assert(app.build_screen._build_action.disabled)
    _check_targets(app.build_screen)
    _shot("ui2_build",bounds)
    print("ui2 layout OK: ",bounds)
    quit(0)
func _check_targets(node: Node) -> void:
    if node is Control and not node.is_visible_in_tree():
        return
    if node is Button or node is OptionButton or node is CheckBox:
        assert(node.size.y >= 48 and node.size.x >= 48, "small target: " + str(node.get_path()))
    if node is Label and node is not RichTextLabel and node is Control:
        if node.autowrap_mode == TextServer.AUTOWRAP_OFF and node.size.x > 0:
            assert(node.get_combined_minimum_size().x <= node.size.x + 4, "clipped label: " + str(node.get_path()))
    for child in node.get_children():
        _check_targets(child)
func _shot(prefix: String,bounds: Vector2i) -> void:
    var dir := OS.get_environment("LUNEX_SCREENSHOT_DIR")
    if dir.is_empty():
        return
    DirAccess.make_dir_recursive_absolute(dir)
    assert(root.get_viewport().get_texture().get_image().save_png(dir.path_join("%s_%dx%d.png" % [prefix,bounds.x,bounds.y])) == OK)
