extends SceneTree
const Supply = preload("res://screens/supply.tscn")
const Store = preload("res://screens/store.tscn")
const WorldApi = preload("res://world/api.gd")
const Mock = preload("res://tests/chain_mock.gd")

func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    var adapter := WorldApi.new()
    root.add_child(adapter)
    var mock := Mock.new()
    root.add_child(mock)
    adapter.mock = Callable(mock, "respond")
    var supply := Supply.instantiate()
    root.add_child(supply)
    await supply.open(adapter, 1)
    for _i in range(5):
        await process_frame
    assert(supply.recipe_rows.get_child_count() > 0)
    assert(supply.row_controls.size() == 1)
    supply._save()
    await process_frame
    assert(mock.calls.has("/enterprises/1/supply"))
    var store := Store.instantiate()
    root.add_child(store)
    await store.open(adapter, 2)
    for _j in range(5):
        await process_frame
    assert(store.rows.get_child_count() > 0)
    assert(store.row_controls.size() == 4)
    store._save()
    await process_frame
    assert(mock.calls.has("/enterprises/2/cells"))
    print("chain screens OK")
    quit(0)
