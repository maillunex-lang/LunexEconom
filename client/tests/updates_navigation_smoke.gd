extends SceneTree
## Regression: the Updates page must be visible after navigation and remain usable.
func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    var app: Control = load("res://main.tscn").instantiate()
    root.add_child(app)
    await process_frame
    await process_frame
    assert(app.router.current == "login")
    app._navigate("updates")
    await process_frame
    assert(app.router.current == "updates")
    assert(app.update_screen.visible, "Updates screen unexpectedly hidden")
    assert(app.update_screen.card.visible and app.update_screen.card.is_visible_in_tree(), "Updates card not visible")
    assert(app.update_screen.message.is_visible_in_tree(), "Updates status not visible")
    assert(app.update_screen.close_button.is_visible_in_tree(), "Close button not visible")
    # A periodic manifest check must not blank the already-open screen.
    app.update_screen.manager.state_changed.emit("Установлена актуальная версия", false, false)
    await process_frame
    assert(app.update_screen.card.is_visible_in_tree(), "Update status blanked the screen")
    app.update_screen._close_panel()
    await process_frame
    assert(app.router.current == "login", "Closing Updates should restore previous screen")
    app._navigate("updates")
    await process_frame
    assert(app.update_screen.card.is_visible_in_tree(), "Updates card missing on second open")
    print("updates navigation smoke OK")
    app.queue_free()
    quit(0)
