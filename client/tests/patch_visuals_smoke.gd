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
    print("PATCH_VISUALS_SMOKE_PASS")
    bridge.queue_free()
    quit()
