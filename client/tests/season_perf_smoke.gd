extends SceneTree
func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    var visual = load("res://season_visual.gd")
    if visual == null:
        push_error("SEASON_SMOKE_FAIL missing visual")
        quit(1)
        return
    var baseline := Color("#63865b")
    assert(visual.season_for_month(0) == 0)
    assert(visual.season_for_month(4) == 1)
    assert(visual.season_for_month(7) == 2)
    assert(visual.season_for_month(10) == 3)
    assert(visual.tinted(baseline, 0) != visual.tinted(baseline, 6))
    assert(visual.tinted(baseline, 6, false) == baseline)
    var host = load("res://world.tscn").instantiate()
    get_root().add_child(host)
    await process_frame
    await process_frame
    var before: bool = host.seasons_enabled
    host._toggle_seasons()
    assert(host.seasons_enabled != before)
    host._toggle_seasons()
    assert(host.seasons_enabled == before)
    var overlay = host.perf_overlay
    assert(overlay != null and not overlay.visible)
    host._toggle_fps()
    assert(overlay.visible)
    overlay.refresh()
    assert(overlay.output.text.contains("FPS") and overlay.output.text.contains("Чанки"))
    host._toggle_fps()
    assert(not overlay.visible)
    print("SEASON_AND_PERF_SMOKE_PASS palette/controls/hud")
    host.queue_free()
    quit(0)
