extends SceneTree
const SIZES := [Vector2i(1280,720),Vector2i(2400,1080),Vector2i(2000,1200),Vector2i(1920,1080),Vector2i(2560,1080)]
const Forest = preload("res://theme/forest_glass.gd")
func _initialize() -> void:
    call_deferred("_run")
func _run() -> void:
    var index := int(OS.get_environment("LUNEX_TEST_SIZE_INDEX"))
    assert(index>=0 and index<SIZES.size())
    var bounds: Vector2i = SIZES[index]
    DisplayServer.window_set_size(bounds)
    root.content_scale_mode = Window.CONTENT_SCALE_MODE_DISABLED
    root.content_scale_size = bounds
    root.size = bounds
    var app: Control = load("res://main.tscn").instantiate()
    root.add_child(app)
    await process_frame
    await process_frame
    await process_frame
    app._on_viewport_resized()
    await process_frame
    assert(app.login_screen.backdrop.size.x >= app.login_screen.size.x-2.0)
    assert(app.login_screen.backdrop.size.y >= app.login_screen.size.y-2.0)
    assert(app.login_screen.card.size.x<=720.1)
    assert(app.login_screen.brand.visible==(bounds.x>=1600))
    _verify_controls(app.login_screen,Forest.touch_size(bounds))
    _capture("ui1_login",bounds)
    app.router.go("updates")
    app.update_screen.open()
    await process_frame
    await process_frame
    assert(app.update_screen.card.size.x<=720.1)
    assert(app.update_screen.card.visible)
    var background: ColorRect = app.update_screen.get_child(0)
    assert(background.size.x>=app.update_screen.size.x-2.0 and background.size.y>=app.update_screen.size.y-2.0)
    _verify_controls(app.update_screen,Forest.touch_size(bounds))
    _capture("ui1_updates",bounds)
    print("ui1 layout OK: ",bounds)
    app.queue_free()
    quit(0)
func _verify_controls(node: Node,minimum: float) -> void:
    if node is Control and node.visible:
        if node is Button or node is LineEdit or node is CheckBox:
            assert(node.size.x + 1>=minimum and node.size.y+1>=minimum,"small touch: "+str(node.get_path())+" "+str(node.size))
        if node is Label:
            # Wrapping labels are allowed to expand vertically within scroll.
            var label: Label = node
            if not label.text.is_empty():
                assert(label.autowrap_mode != TextServer.AUTOWRAP_OFF or label.get_combined_minimum_size().x<=label.size.x+2,"clipped label: "+str(label.get_path()))
        if node is Button:
            var button: Button = node
            assert(button.get_combined_minimum_size().x<=button.size.x+2,"clipped button: "+str(button.get_path()))
    for child in node.get_children():
        if child is Control:
            if child.visible: _verify_controls(child,minimum)
        elif child is Node:
            _verify_controls(child,minimum)
func _capture(name: String,bounds: Vector2i) -> void:
    var folder := OS.get_environment("LUNEX_SCREENSHOT_DIR")
    if folder.is_empty(): return
    DirAccess.make_dir_recursive_absolute(folder)
    var path := folder.path_join("%s_%dx%d.png"%[name,bounds.x,bounds.y])
    assert(root.get_viewport().get_texture().get_image().save_png(path)==OK)
    print("screenshot: ",path)
