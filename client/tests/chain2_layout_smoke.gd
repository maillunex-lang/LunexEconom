extends SceneTree
const Mock = preload("res://tests/chain2_mock.gd")
const Adapter = preload("res://world/api.gd")
const Enterprises = preload("res://screens/enterprises.tscn")
const Build = preload("res://screens/build.tscn")
const Store = preload("res://screens/store.tscn")
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
    var mock := Mock.new()
    root.add_child(mock)
    var adapter := Adapter.new()
    root.add_child(adapter)
    adapter.mock = Callable(mock, "respond")
    var enterprises := Enterprises.instantiate()
    root.add_child(enterprises)
    enterprises.service.configure(adapter)
    enterprises.catalog.configure(adapter)
    assert(await enterprises.catalog.update())
    await enterprises.show_detail(1)
    await process_frame
    assert(enterprises.size.x <= bounds.x)
    _shot("chain2_materials_short", bounds)
    enterprises.hide()
    var build := Build.instantiate()
    root.add_child(build)
    build.catalog.configure(adapter)
    build.service.configure(adapter)
    build.zone = "free"
    build.wallet_balance = 999999
    await build._load()
    await process_frame
    assert(build.rows.get_child_count() == 42)
    assert(build.size.x <= bounds.x)
    _shot("chain2_catalog_42", bounds)
    build.hide()
    var store := Store.instantiate()
    root.add_child(store)
    await store.open(adapter,2)
    await process_frame
    assert(store.row_controls.size() == 1)
    assert(store.size.x <= bounds.x)
    _shot("chain2_fuel_station", bounds)
    print("chain2 layout OK: ", bounds)
    quit(0)

func _shot(prefix: String, bounds: Vector2i) -> void:
    var folder := OS.get_environment("LUNEX_SCREENSHOT_DIR")
    if folder.is_empty():
        return
    DirAccess.make_dir_recursive_absolute(folder)
    var path := folder.path_join("%s_%dx%d.png" % [prefix,bounds.x,bounds.y])
    assert(root.get_viewport().get_texture().get_image().save_png(path) == OK)
    print("screenshot: ", path)
