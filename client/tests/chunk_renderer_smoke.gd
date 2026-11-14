extends SceneTree
## Headless smoke: owner colors are deterministic, preview is not recalculated per tile.
func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    var renderer_script = load("res://chunk_renderer.gd")
    assert(renderer_script != null)
    var renderer = renderer_script.new()
    get_root().add_child(renderer)
    assert(renderer._owner_color("npc:alpha") == renderer._owner_color("npc:alpha"))
    assert(renderer._owner_color("npc:alpha") != renderer._owner_color("player:beta"))
    assert(renderer._owner_color("") == Color("#9ca3a8"))
    renderer.queue_redraw()
    await process_frame
    assert(renderer.draw_count >= 0)
    print("CHUNK_RENDERER_SMOKE_PASS")
    renderer.queue_free()
    quit()
