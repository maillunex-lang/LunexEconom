extends SceneTree

func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    var app: Control = load("res://main.tscn").instantiate()
    root.add_child(app)
    await process_frame
    await process_frame
    app.router.go("more")
    app.more_screen._activate("model_viewer")
    await process_frame
    assert(app.router.current == "model_viewer")
    var viewer: Control = app.model_viewer_screen
    assert(viewer.entries.size() == 64)
    assert(viewer.selected["id"] == "field")
    assert(viewer.stats_label.text.contains("Треугольников"))
    assert(viewer.error_label.text == "", "failed GLB initial import")
    viewer.set_stage(0)
    for i in range(viewer.STAGES.size()):
        var stage: Node = viewer.model_anchor.get_child(0).find_child(viewer.STAGES[i],true,false)
        assert(stage.visible == (i == 0))
    viewer.set_stage(4)
    viewer.category_widget.select(2)
    viewer._set_filter()
    assert(viewer.list_widget.item_count == 22)
    viewer._on_list_selected(0)
    assert(viewer.selected["family"] == "city")
    viewer.category_widget.select(1)
    viewer._set_filter()
    assert(viewer.list_widget.item_count == 42)
    viewer._select_entry({"id":"missing","family":"buildings","width":3,"height":2})
    assert(viewer.error_label.text != "")
    assert(viewer.model_anchor.get_child_count()==1)
    viewer.back_requested.emit()
    assert(app.router.current=="more")
    app.router.go("settings")
    app.settings_screen.model_viewer_requested.emit()
    assert(app.router.current == "model_viewer")
    print("models viewer smoke OK: router, category filters, 5 stages, stats, fallback")
    app.queue_free()
    quit(0)
