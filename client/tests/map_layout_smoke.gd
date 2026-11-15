extends SceneTree
const Mock = preload("res://tests/world_mock.gd")
const SIZES := [Vector2i(1280,720),Vector2i(2400,1080),Vector2i(2000,1200),Vector2i(1920,1080)]
func _initialize() -> void:
    call_deferred("_run")
func _run() -> void:
    var index: int = int(OS.get_environment("LUNEX_TEST_SIZE_INDEX"))
    assert(index>=0 and index<SIZES.size())
    var bounds: Vector2i = SIZES[index]
    DisplayServer.window_set_size(bounds)
    root.content_scale_mode=Window.CONTENT_SCALE_MODE_DISABLED
    root.content_scale_size=bounds
    root.size=bounds
    var app: Control = load("res://main.tscn").instantiate()
    root.add_child(app)
    await process_frame
    await process_frame
    var mock := Mock.new()
    root.add_child(mock)
    app.map_screen.api.mock=Callable(mock,"respond")
    app._show_headquarters()
    app._navigate("map")
    for i in range(420):
        await process_frame
        if app.map_screen.stream.chunks.size() == app.map_screen.stream.desired.size() and app.map_screen.stream.desired.size() > 0:
            break
    await process_frame
    assert(app.router.current=="map")
    assert(app.map_screen.options.item_count==20)
    assert(app.map_screen.canvas.tiles.size()>0,"no rendered chunks")
    assert(app.map_screen.stream.chunks.size() == app.map_screen.stream.desired.size(),"chunks not fully rendered")
    var header: HBoxContainer = app.map_screen.get_node("MapLayout/MapHeader")
    for child in header.get_children():
        if child is Control:
            assert(child.position.x>=0)
            if child is Button or child is OptionButton:
                assert(child.size.y>=48, "touch target too small")
            assert(child.position.x+child.size.x<=bounds.x+1,"map header clipped")
    assert(app.map_screen.get_node("MapLayout/MapHeader/MapTitle").text=="Карта")
    var out: String = OS.get_environment("LUNEX_SCREENSHOT_DIR")
    if not out.is_empty():
        DirAccess.make_dir_recursive_absolute(out)
        var filename := out.path_join("map_%dx%d.png" % [bounds.x,bounds.y])
        assert(root.get_viewport().get_texture().get_image().save_png(filename)==OK)
        print("screenshot: ",filename)
    var draw_calls := RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_TOTAL_DRAW_CALLS_IN_FRAME)
    assert(draw_calls <= 2000,"draw-call budget exceeded")
    print("map layout OK ",bounds," chunks=",app.map_screen.canvas.tiles.size()," draw_calls=",draw_calls)
    app.queue_free()
    quit(0)
