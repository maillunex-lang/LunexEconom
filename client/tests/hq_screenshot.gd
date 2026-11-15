extends SceneTree
## Use xvfb-run with the standard Godot rendering driver.
func _initialize() -> void:
    call_deferred("_run")
func _run() -> void:
    root.size = Vector2i(1280, 720)
    var screen = load("res://hq.tscn").instantiate()
    root.add_child(screen)
    screen.sample_mode = true
    screen._set_active(false)
    screen.apply_hq(load("res://hq/hq_api.gd").sample())
    for i in 8:
        await process_frame
    var dir: String = OS.get_cmdline_user_args()[0] if not OS.get_cmdline_user_args().is_empty() else "user://"
    var output := dir.path_join("hq_1280.png")
    var err := root.get_texture().get_image().save_png(output)
    print("HQ_SCREENSHOT ", output, " err=", err)
    quit(0 if err == OK else 1)
