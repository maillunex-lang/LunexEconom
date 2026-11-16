extends SceneTree
const SIZES := [Vector2i(1280,720),Vector2i(2400,1080),Vector2i(2000,1200),Vector2i(1920,1080)]
const IDS := ["field","oil_well","refinery","apiary","mill","bakery","fuel_station","mosque","hospital","city_hall"]

func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    var index := int(OS.get_environment("LUNEX_TEST_SIZE_INDEX"))
    assert(index>=0 and index<SIZES.size())
    var bounds: Vector2i = SIZES[index]
    DisplayServer.window_set_size(bounds)
    root.content_scale_mode = Window.CONTENT_SCALE_MODE_DISABLED
    root.content_scale_size = bounds
    root.size = bounds
    var app: Control = load("res://main.tscn").instantiate()
    root.add_child(app)
    for i in range(5):
        await process_frame
    app.router.go("model_viewer")
    app._on_viewport_resized()
    var viewer: Control = app.model_viewer_screen
    for i in range(5):
        await process_frame
    var layout: Control = viewer.get_node("ViewerLayout")
    var split: Control = layout.get_node("ViewerSplit")
    assert(viewer.size.x <= bounds.x+1 and viewer.size.y <= bounds.y+1)
    assert(split.size.x > 500,"viewer split clipped")
    assert(viewer.viewport_container.size.x >= 250,"preview width clipped")
    assert(viewer.viewport_container.size.y >= 250,"preview height clipped")
    assert(viewer.list_widget.size.x >= 180)
    assert(viewer.category_widget.size.y >= 48)
    assert(viewer.stage_widget.size.y > 0)
    assert(viewer.error_label.text == "")
    var output := OS.get_environment("LUNEX_SCREENSHOT_DIR")
    if not output.is_empty():
        DirAccess.make_dir_recursive_absolute(output)
        if index == 0:
            for id in IDS:
                var found: Dictionary = {}
                for e in viewer.entries:
                    if str(e.get("id","")) == id:
                        found=e
                        break
                assert(not found.is_empty())
                viewer._select_entry(found)
                for frame in range(6):
                    await process_frame
                var path := output.path_join("model_%s_%dx%d.png" % [id,bounds.x,bounds.y])
                assert(root.get_viewport().get_texture().get_image().save_png(path)==OK)
        else:
            var path := output.path_join("model_layout_%dx%d.png" % [bounds.x,bounds.y])
            assert(root.get_viewport().get_texture().get_image().save_png(path)==OK)
    print("models layout OK ",bounds)
    app.queue_free()
    quit(0)
