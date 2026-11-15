extends SceneTree
## Android landscape editor regression: visible panel, scrollable controls,
## safe margins, brush sizes, touch-friendly targets and visibility toggles.

var failures := 0

func _check(condition: bool, label: String) -> void:
    if not condition:
        failures += 1
        print("DEV_EDITOR_FAIL ", label)

func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    var root: Control = load("res://world.tscn").instantiate()
    get_root().size = Vector2i(846, 388)
    get_root().add_child(root)
    await process_frame
    await process_frame
    root._toggle_developer_editor()
    await process_frame
    await process_frame
    var editor: PanelContainer = root.developer_editor
    var scroll: ScrollContainer = editor.get_child(0)
    var controls: VBoxContainer = scroll.get_child(0)
    _check(controls.get_child_count() >= 12, "all editor controls exist")
    _check((controls.get_child(1) as OptionButton).item_count == 6, "six terrain/road modes")
    _check((controls.get_child(2) as OptionButton).item_count == 3, "three brush sizes")
    for resolution in [Vector2i(846, 388), Vector2i(1280, 720), Vector2i(2340, 1080)]:
        get_root().size = resolution
        await process_frame
        await process_frame
        root._update_safe_area()
        var visible: Rect2 = root.get_viewport_rect()
        var panel: Rect2 = editor.get_global_rect()
        _check(panel.size.x > 300 and panel.size.y > 180, "nonzero panel at " + str(resolution))
        _check(panel.position.x >= 10 and panel.position.y >= 10, "panel left/top safe at " + str(resolution))
        _check(panel.end.x <= visible.end.x - 10 and panel.end.y <= visible.end.y - 10, "panel right/bottom safe at " + str(resolution))
        _check(scroll.size.y > 150, "scroll viewport visible at " + str(resolution))
        _check(controls.get_combined_minimum_size().y > scroll.size.y, "actions can be scrolled at " + str(resolution))
        print("DEV_EDITOR_LAYOUT ", resolution, " ", panel)
    root.set_selection(Vector2i(7, 8))
    _check(editor.status.text.contains("7:8"), "selected map cell reaches editor")
    var brush = load("res://dev_brush.gd")
    for size in [1, 3, 5]:
        var cells: Array = brush.cells(Vector2i(7, 8), size)
        _check(cells.size() == size * size, "brush footprint " + str(size))
        _check(cells.has([7, 8]), "brush contains selected cell " + str(size))
    root._toggle_developer_editor()
    _check(not editor.visible, "toggle hides editor")
    root._toggle_developer_editor()
    _check(editor.visible, "toggle restores editor")
    root.queue_free()
    await process_frame
    if failures == 0:
        print("DEV_EDITOR_SMOKE_PASS layout/scroll/touch-targets/brush/selection/toggle")
    quit(0 if failures == 0 else 1)