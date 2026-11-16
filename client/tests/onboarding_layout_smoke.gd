extends SceneTree
const Mock = preload("res://tests/onboarding_mock.gd")
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
    await process_frame
    var mock := Mock.new()
    root.add_child(mock)
    app.map_screen.api.mock = Callable(mock,"respond")
    # The map stream's deferred session restore must not interrupt this
    # screenshot scenario; the layout runner has no login access token.
    app.map_screen.api.base_url = "https://onboard-mock.invalid/api"
    app.base_url = "https://onboard-mock.invalid/api"
    app._show_headquarters()
    # Force a stable local layout scenario without calling production updater.
    app.update_screen.manager.current_version_code = 999999
    app.update_screen.manager.manifest = {}
    app.update_screen.mandatory = false
    app.tutorial_state.use_account(mock.mock_account)
    app.tutorial_state.step = 3
    app.tutorial_guide.set_progress(app.tutorial_state)
    app._on_viewport_resized()
    await process_frame
    _check_nav(app,bounds,"headquarters")
    _shot("onboarding_hq",bounds)
    app._navigate("map")
    app.update_screen.mandatory = false
    for i in range(440):
        await process_frame
        if app.map_screen.canvas.tiles.size()>0 and app.map_screen.stream.chunks.size()==app.map_screen.stream.desired.size():
            break
    assert(app.router.current == "map", "map navigation interrupted")
    assert(app.map_screen.canvas.tiles.size()>0, "map chunks missing")
    _check_nav(app,bounds,"map")
    _shot("onboarding_map",bounds)
    app.router.go("settings")
    await process_frame
    _check_nav(app,bounds,"settings")
    _shot("onboarding_settings",bounds)
    app.router.go("more")
    await process_frame
    _check_nav(app,bounds,"more")
    _shot("onboarding_more",bounds)
    app.router.go("finance")
    await process_frame
    _check_nav(app,bounds,"finance")
    _shot("onboarding_finance",bounds)
    app.router.go("build")
    app.build_screen.open(app.map_screen.api, {"px":2,"py":0,"zone":"free","site_cells":[]}, Vector2i(14,3))
    for i in range(70):
        await process_frame
        if app.build_screen.rows.get_child_count()>0:
            break
    assert(app.build_screen.rows.get_child_count()>0)
    app.build_screen._choose(mock.BUILDING_CATALOG[0], {"x":14,"y":3})
    await create_timer(0.4).timeout
    await process_frame
    app.build_screen.confirmation.hide()
    assert(app.build_screen.preview_canvas.road_preview.size()==2)
    assert(not app.navigation_bar.visible)
    _shot("onboarding_build_road",bounds)
    print("onboarding layout OK ",bounds)
    app.queue_free()
    quit(0)

func _check_nav(app: Control, bounds: Vector2i, screen: String) -> void:
    assert(app.navigation_bar.visible, "nav hidden at " + screen)
    assert(app.navigation_bar.position.x>=0)
    assert(app.navigation_bar.position.x+app.navigation_bar.size.x <= bounds.x+1)
    assert(app.navigation_bar.position.y+app.navigation_bar.size.y <= bounds.y+1)
    for button in app.navigation_bar.buttons.values():
        assert(button.size.y>=48 and button.size.x>=48, "touch target too small")

func _shot(prefix: String, bounds: Vector2i) -> void:
    var folder := OS.get_environment("LUNEX_SCREENSHOT_DIR")
    if folder.is_empty():
        return
    DirAccess.make_dir_recursive_absolute(folder)
    var path := folder.path_join("%s_%dx%d.png" % [prefix,bounds.x,bounds.y])
    assert(root.get_viewport().get_texture().get_image().save_png(path)==OK)
    print("screenshot: ",path)