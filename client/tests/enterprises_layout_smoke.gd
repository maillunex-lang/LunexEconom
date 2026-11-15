extends SceneTree
const Mock = preload("res://tests/enterprises_mock.gd")
const SIZES := [Vector2i(1280,720),Vector2i(2400,1080),Vector2i(2000,1200),Vector2i(1920,1080)]
func _initialize() -> void:
    call_deferred("_run")
func _run() -> void:
    var index := int(OS.get_environment("LUNEX_TEST_SIZE_INDEX"))
    assert(index >= 0 and index < SIZES.size())
    var bounds: Vector2i = SIZES[index]
    DisplayServer.window_set_size(bounds)
    root.content_scale_mode = Window.CONTENT_SCALE_MODE_DISABLED
    root.content_scale_size = bounds
    root.size = bounds
    var app: Control = load("res://main.tscn").instantiate()
    root.add_child(app)
    await process_frame
    var mock := Mock.new()
    root.add_child(mock)
    app.map_screen.api.mock = Callable(mock,"respond")
    app._show_headquarters()
    app._navigate("enterprises")
    for i in range(12):
        await process_frame
    assert(app.router.current == "enterprises")
    assert(app.enterprises_screen.body.get_child_count() > 0)
    _screenshot("enterprises_list",bounds)
    await app.enterprises_screen.show_detail(1)
    for i in range(4):
        await process_frame
    assert(app.enterprises_screen.current_id == 1)
    _screenshot("enterprises_detail",bounds)
    app._on_build_requested({"px":1,"py":2,"zone":"free","owner_kind":"player"},Vector2i(6,12))
    for i in range(8):
        await process_frame
    assert(app.router.current == "build")
    assert(app.build_screen.rows.get_child_count() > 0)
    _screenshot("building_picker",bounds)
    print("enterprise layout OK ",bounds)
    app.queue_free()
    quit(0)
func _screenshot(prefix: String, bounds: Vector2i) -> void:
    var directory := OS.get_environment("LUNEX_SCREENSHOT_DIR")
    if directory.is_empty():
        return
    DirAccess.make_dir_recursive_absolute(directory)
    var path := directory.path_join("%s_%dx%d.png" % [prefix,bounds.x,bounds.y])
    assert(root.get_viewport().get_texture().get_image().save_png(path) == OK)
    print("screenshot: ",path)
