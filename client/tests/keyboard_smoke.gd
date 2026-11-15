extends SceneTree
func _initialize() -> void:
    call_deferred("_run")
func _run() -> void:
    var instance: Control = load("res://main.tscn").instantiate()
    root.add_child(instance)
    await process_frame
    await process_frame
    instance.shell.add_theme_constant_override("margin_bottom",400)
    instance.login_screen.resize_ui(Vector2(1280,720),400)
    await process_frame
    await process_frame
    assert(instance.login_screen.scroll.size.y <= 330.0)
    instance.login_password.grab_focus()
    await process_frame
    instance.login_screen._scroll_focused()
    await process_frame
    await process_frame
    var view: ScrollContainer = instance.login_screen.scroll
    assert(view.scroll_vertical >= 0)
    # The password field must end within the remaining scrolled viewport.
    var password: LineEdit = instance.login_password
    var visible_end: float = view.global_position.y + view.size.y
    assert(password.global_position.y + password.size.y <= visible_end + 4.0)
    print("keyboard smoke OK: focused password visible after simulated virtual keyboard")
    quit(0)
