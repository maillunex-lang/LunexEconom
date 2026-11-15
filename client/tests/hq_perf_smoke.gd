extends SceneTree
## Bounded headless benchmark; renderer and CPU characteristics are not Android watt-hours.
func _initialize() -> void:
    call_deferred("_run")

func _measure(scene_path: String, frames: int) -> Dictionary:
    var started := Time.get_ticks_usec()
    var host = load(scene_path).instantiate()
    root.add_child(host)
    await process_frame
    if scene_path == "res://hq.tscn":
        host._set_active(false)
        host.sample_mode = true
        host.apply_hq(load("res://hq/hq_api.gd").sample())
        host._set_active(true)
        host.show_performance = true
    var first := Time.get_ticks_usec()
    var max_frame := 0.0
    var frame_sum := 0.0
    for i in frames:
        await process_frame
        var frame_time := Performance.get_monitor(Performance.TIME_PROCESS) * 1000.0
        frame_sum += frame_time
        max_frame = maxf(max_frame, frame_time)
    var stats := {
        "name": scene_path, "frames": frames,
        "frame_ms_avg": snappedf(frame_sum / float(frames), 0.001),
        "frame_ms_peak": snappedf(max_frame, 0.001),
        "wall_ms": snappedf(float(Time.get_ticks_usec() - first) / 1000.0, 0.01),
        "scene_load_ms": snappedf(float(first - started) / 1000.0, 0.01),
        "fps_limit": Engine.max_fps
    }
    host.queue_free()
    await process_frame
    return stats

func _run() -> void:
    var headquarters: Dictionary = await _measure("res://hq.tscn", 90)
    var map: Dictionary = await _measure("res://world.tscn", 90)
    print("HQ_PERF_HEADQUARTERS ", JSON.stringify(headquarters))
    print("HQ_PERF_MAP ", JSON.stringify(map))
    print("HQ_PERF_SMOKE_PASS")
    quit()