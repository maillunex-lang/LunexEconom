extends SceneTree
var failures := 0

func _initialize() -> void:
    call_deferred("_run")

func _check(ok: bool, description: String) -> void:
    if not ok:
        failures += 1
        print("FAIL ", description)

func _run() -> void:
    var hq = load("res://hq.tscn").instantiate()
    root.add_child(hq)
    await process_frame
    hq._set_active(false)
    hq.sample_mode = true
    var data = load("res://hq/hq_api.gd").sample()
    _check(data is Dictionary and data.has("enterprises"), "sample contract")
    hq.apply_hq(data)
    _check(hq.title_label.text == "Башкирский холдинг", "company header")
    _check(hq.content.find_child("FinancialChart", true, false) != null, "static chart")
    _check(hq.content.find_children("*", "Button", true, false).size() >= 2, "enterprise actions")
    _check(hq.notifications.get_child_count() >= 3, "alerts")
    _check(not _contains_3d(hq), "headquarters has zero Node3D")
    hq.open_section("Предприятия")
    _check(hq.content.find_children("*", "Button", true, false).size() >= 4, "two enterprises and controls")
    var before: int = hq.count_requests
    await create_timer(0.12).timeout
    _check(hq.count_requests == before and hq.poll_timer.is_stopped(), "hidden HQ never polls")
    hq.open_section("Финансы")
    _check(hq.content.find_child("Endpoint_wallet", true, false) != null, "finance uses wallet")
    hq.open_section("Рынок и биржа")
    _check(hq.content.find_child("Endpoint_market", true, false) != null, "market section")
    var source = load("res://world.gd")
    _check(source != null and source.new().has_method("focus_cell") and source.new().has_method("select_cell"), "real world focusing API")
    var captured := [Vector2i(-1, -1)]
    hq.map_requested.connect(func(cell: Vector2i) -> void:
        captured[0] = cell
    )
    # Signal and scene focus metadata are checked independently from the expensive world scene.
    hq._desired_focus = Vector2i(40, 12)
    hq.map_requested.emit(hq._desired_focus)
    _check(captured[0] == Vector2i(40, 12), "map requests focus at enterprise")
    _check(hq._money(1250000).contains("1 250 000"), "money formatting")
    hq.queue_free()
    await process_frame
    if failures == 0:
        print("HQ_SMOKE_PASS")
    quit(0 if failures == 0 else 1)

func _contains_3d(node: Node) -> bool:
    if node is Node3D:
        return true
    for child in node.get_children():
        if _contains_3d(child):
            return true
    return false