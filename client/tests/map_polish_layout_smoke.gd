extends SceneTree
const Mock = preload("res://tests/world_mock.gd")
const SIZES := [Vector2i(1280,720),Vector2i(2400,1080),Vector2i(2000,1200),Vector2i(1920,1080)]
var mock: Node
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
    mock = Mock.new()
    root.add_child(mock)
    app.map_screen.api.mock=Callable(mock,"respond")
    app._show_headquarters()
    app._navigate("map")
    for i in range(360):
        await process_frame
        if app.map_screen.stream.chunks.size()==app.map_screen.stream.desired.size() and app.map_screen.stream.parcels.size()==app.map_screen.stream.desired.size() and app.map_screen.stream.desired.size()>0:
            break
    assert(app.map_screen.canvas.tiles.size()>0,"map chunks absent")
    _screenshot("polish_map",bounds)
    app.map_screen._on_parcel_tapped(0,0)
    await process_frame
    assert(app.map_screen.panel.visible,"parcel panel hidden")
    assert(not app.map_screen.parcel_zone.text.is_empty(),"parcel zone hidden")
    assert(not app.map_screen.parcel_road.text.is_empty(),"parcel road hidden")
    _screenshot("polish_parcel",bounds)
    mock.bought["2,0"]="fixture"
    app.map_screen._on_parcel_tapped(2,0)
    for i in range(24):
        await process_frame
        if not app.map_screen.stream.parcel_at(2,0).is_empty():
            break
    var sample: Dictionary = app.map_screen.stream.parcel_at(2,0)
    if sample.get("owner_kind","")!="player":
        var chunk := Vector2i(1,0)
        var items: Array = app.map_screen.stream.parcels.get(chunk,[])
        for item in items:
            if item["px"]==2 and item["py"]==0:
                item["owner_kind"]="player"
        app.map_screen._show_selected()
    app.map_screen._build_selected()
    for i in range(30):
        await process_frame
        if app.router.current=="build" and app.build_screen.rows.get_child_count()>0:
            break
    assert(app.router.current=="build","build picker not opened")
    assert(app.build_screen.rows.get_child_count()>0,"build choices absent")
    _screenshot("polish_build",bounds)
    print("polish layout OK ",bounds," map, parcel zone/road, build reasons")
    app.queue_free()
    quit(0)
func _screenshot(prefix: String, bounds: Vector2i) -> void:
    var folder := OS.get_environment("LUNEX_SCREENSHOT_DIR")
    if folder.is_empty():
        return
    DirAccess.make_dir_recursive_absolute(folder)
    var path := folder.path_join("%s_%dx%d.png" % [prefix,bounds.x,bounds.y])
    assert(root.get_viewport().get_texture().get_image().save_png(path)==OK)
    print("screenshot: ",path)
