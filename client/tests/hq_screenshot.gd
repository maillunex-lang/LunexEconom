extends SceneTree
func _initialize() -> void:
    call_deferred("_run")
func _run() -> void:
    var dir: String = OS.get_cmdline_user_args()[0] if not OS.get_cmdline_user_args().is_empty() else "user://"
    for resolution in [Vector2i(846, 388), Vector2i(1280, 720), Vector2i(2340, 1080)]:
        root.content_scale_size = resolution
        root.size = resolution
        var screen = load("res://hq.tscn").instantiate()
        root.add_child(screen)
        screen.sample_mode = true
        screen._set_active(false)
        screen.apply_hq(load("res://hq/hq_api.gd").sample())
        for i in 8:
            await process_frame
        var output := dir.path_join("hq_%d_%d.png" % [resolution.x, resolution.y])
        var err := root.get_texture().get_image().save_png(output)
        print("HQ_SCREENSHOT ", output, " err=", err)
        screen.queue_free()
        await process_frame
        if err != OK:
            quit(1)
            return
    quit(0)
