extends SceneTree
const Supply = preload("res://screens/supply.tscn")
const Store = preload("res://screens/store.tscn")
const WorldApi = preload("res://world/api.gd")
const Mock = preload("res://tests/chain_mock.gd")
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
    var adapter := WorldApi.new()
    root.add_child(adapter)
    var mock := Mock.new()
    root.add_child(mock)
    adapter.mock = Callable(mock, "respond")
    var supply := Supply.instantiate()
    root.add_child(supply)
    await supply.open(adapter, 1)
    await process_frame
    _shot("supply", bounds)
    var store := Store.instantiate()
    root.add_child(store)
    await store.open(adapter, 2)
    await process_frame
    _shot("store", bounds)
    assert(supply.size.x <= bounds.x and store.size.x <= bounds.x)
    print("chain layout OK ", bounds)
    quit(0)

func _shot(name: String, bounds: Vector2i) -> void:
    var directory := OS.get_environment("LUNEX_SCREENSHOT_DIR")
    if directory.is_empty():
        return
    DirAccess.make_dir_recursive_absolute(directory)
    var path := directory.path_join("%s_%dx%d.png" % [name, bounds.x, bounds.y])
    assert(root.get_viewport().get_texture().get_image().save_png(path) == OK)
