extends SceneTree
func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    var bridge_script = load("res://patch_visuals.gd")
    assert(bridge_script != null)
    var bridge = bridge_script.new()
    get_root().add_child(bridge)
    assert(bridge.texture_for("school") == null)
    assert(not bridge.activate_from_cache())
    assert(bridge.active_revision == 0)
    var world_script = load("res://world.gd")
    assert(world_script != null)
    var world = world_script.new()
    get_root().add_child(world)
    await process_frame
    assert(world.patch_visuals != null)
    assert(world.patch_visuals.texture_for("factory") == null)
    print("PATCH_VISUALS_SMOKE_PASS")
    world.queue_free()
    bridge.queue_free()
    quit()
