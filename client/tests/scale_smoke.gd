extends SceneTree
const Forest = preload("res://theme/forest_glass.gd")
const SIZES := [Vector2i(1280,720),Vector2i(2400,1080),Vector2i(2000,1200),Vector2i(1920,1080)]
func _initialize() -> void:
    call_deferred("_run")
func _run() -> void:
    var test_window: int = int(OS.get_environment("LUNEX_TEST_SIZE_INDEX"))
    assert(test_window >= 0 and test_window < SIZES.size())
    var bounds: Vector2i = SIZES[test_window]
    DisplayServer.window_set_size(bounds)
    root.content_scale_mode = Window.CONTENT_SCALE_MODE_DISABLED
    root.content_scale_size = bounds
    root.size = bounds
    var instance: Control = load("res://main.tscn").instantiate()
    root.add_child(instance)
    await process_frame
    await process_frame
    await process_frame
    instance._on_viewport_resized()
    await process_frame
    assert(instance.theme.default_font_size >= 16)
    assert(load("res://theme/forest_glass.tres") is Theme)
    var bad: Array[String] = []
    _check_touches(instance.login_screen,Forest.touch_size(instance.get_viewport_rect().size),bad)
    _capture("login",bounds)
    instance._show_headquarters()
    await process_frame
    _check_touches(instance.headquarters_screen,Forest.touch_size(instance.get_viewport_rect().size),bad)
    _capture("headquarters",bounds)
    instance.router.go("settings")
    await process_frame
    _check_touches(instance.settings_screen,Forest.touch_size(instance.get_viewport_rect().size),bad)
    _capture("settings",bounds)
    instance.router.go("updates")
    await process_frame
    _check_touches(instance.update_screen,Forest.touch_size(instance.get_viewport_rect().size),bad)
    _capture("updates",bounds)
    instance.router.reset("login")
    await process_frame
    assert(bad.is_empty(), "touch targets below 48dp: " + ", ".join(bad))
    print("scale smoke OK: ",bounds," min target ",Forest.touch_size(instance.get_viewport_rect().size),"px")
    instance.queue_free()
    quit(0)

func _check_touches(node: Node, minimum: float, bad: Array[String]) -> void:
    if node is Button or node is LineEdit or node is CheckBox:
        if node.size.y + 0.1 < minimum or node.size.x + 0.1 < minimum:
            bad.append(str(node.get_path()) + "=" + str(node.size))
    for child in node.get_children():
        _check_touches(child,minimum,bad)

func _capture(name: String, bounds: Vector2i) -> void:
    var dir: String = OS.get_environment("LUNEX_SCREENSHOT_DIR")
    if dir.is_empty():
        return
    DirAccess.make_dir_recursive_absolute(dir)
    var filename := dir.path_join("%s_%sx%s.png" % [name,bounds.x,bounds.y])
    var err := root.get_viewport().get_texture().get_image().save_png(filename)
    assert(err == OK)
    print("screenshot: ",filename)
