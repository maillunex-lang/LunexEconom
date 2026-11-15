extends SceneTree
var failures := 0
func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    for viewport_size in [Vector2i(846, 388), Vector2i(1280, 720), Vector2i(2340, 1080)]:
        root.content_scale_size = viewport_size
        root.size = viewport_size
        var host = load("res://hq.tscn").instantiate()
        root.add_child(host)
        host._set_active(false)
        host.apply_hq(load("res://hq/hq_api.gd").sample())
        host._layout()
        await process_frame
        await process_frame
        var size: Vector2 = host.get_viewport_rect().size
        var safe: Rect2 = host.root_margin.get_global_rect()
        if safe.size.x < 300 or safe.size.y < 160:
            failures += 1
            print("FAIL content area ", viewport_size, " ", safe)
        if host.left_nav.size.y < 90 or host.body_scroll.size.y < 90:
            failures += 1
            print("FAIL scroll regions ", viewport_size)
        if host.top_buttons.size.y < 48:
            failures += 1
            print("FAIL tap targets ", viewport_size)
        print("HQ_LAYOUT_CHECK ", viewport_size, " center=", host.body_scroll.size)
        host.queue_free()
        await process_frame
    if failures == 0:
        print("HQ_LAYOUT_SMOKE_PASS")
    quit(0 if failures == 0 else 1)