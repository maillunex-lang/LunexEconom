extends SceneTree

func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    var scene := load("res://main.tscn")
    assert(scene != null)
    var instance: Node = scene.instantiate()
    root.add_child(instance)
    await process_frame
    await process_frame
    assert(instance.get_node_or_null(".") != null)
    assert(instance.get("form") != null)
    assert(instance.get("headquarters") != null)
    assert(not instance.get("headquarters").visible)
    assert(DisplayServer.window_get_size().x >= DisplayServer.window_get_size().y)
    print("V2 client smoke OK: login, HQ, landscape")
    quit(0)
