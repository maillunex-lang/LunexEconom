extends SceneTree
const SIZES := [Vector2i(1280,720),Vector2i(2400,1080),Vector2i(2000,1200),Vector2i(1920,1080),Vector2i(2560,1080)]
func _initialize() -> void:
    call_deferred("_run")
func _run() -> void:
    var i := int(OS.get_environment("LUNEX_TEST_SIZE_INDEX"))
    assert(i >= 0 and i < SIZES.size())
    var bounds: Vector2i = SIZES[i]
    DisplayServer.window_set_size(bounds)
    root.content_scale_mode = Window.CONTENT_SCALE_MODE_DISABLED
    root.content_scale_size = bounds
    root.size = bounds
    var app: Control = load("res://main.tscn").instantiate()
    root.add_child(app)
    for f in range(4):
        await process_frame
    app._on_viewport_resized()
    await process_frame
    assert(app.login_screen.card.size.x <= 721)
    assert(app.login_screen.brand.visible == (bounds.x >= 1600))
    _check(app.login_screen,"login")
    _capture("ui1_login",bounds)
    app.router.go("updates")
    app.update_screen.open()
    await process_frame
    assert(app.update_screen.card.size.x <= 721)
    _check(app.update_screen,"updates")
    _capture("ui1_updates",bounds)
    print("ui1 layout OK: ",bounds)
    app.queue_free()
    quit(0)

func _check(node: Node, scene: String) -> void:
    if node is Control and not node.visible:
        return
    if node is Button or node is LineEdit or node is CheckBox:
        assert(node.size.x + 0.5 >= 48.0 and node.size.y + 0.5 >= 48.0, scene + ": small target " + str(node.get_path()) + " " + str(node.size))
    if node is Label:
        assert(node.autowrap_mode != TextServer.AUTOWRAP_OFF or node.get_combined_minimum_size().x <= node.size.x + 2.0, scene + ": text clipped " + str(node.get_path()) + " " + str(node.size))
    if node is Button:
        assert(node.get_combined_minimum_size().x <= node.size.x + 2.0, scene + ": button clipped " + str(node.get_path()))
    for child in node.get_children():
        _check(child,scene)

func _capture(name: String,bounds: Vector2i) -> void:
    var dir := OS.get_environment("LUNEX_SCREENSHOT_DIR")
    if dir.is_empty():
        return
    DirAccess.make_dir_recursive_absolute(dir)
    assert(root.get_viewport().get_texture().get_image().save_png(dir.path_join("%s_%dx%d.png" % [name,bounds.x,bounds.y])) == OK)
