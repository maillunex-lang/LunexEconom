extends SceneTree
const Router = preload("res://screens/router.gd")
const Safe = preload("res://ui/safe_area.gd")
const Keyboard = preload("res://ui/keyboard.gd")
func _initialize() -> void:
    call_deferred("_run")
func _run() -> void:
    var router := Router.new()
    root.add_child(router)
    await process_frame
    for key in Router.SCREENS:
        var page := Control.new()
        router.register_screen(key,page)
    router.reset("login")
    assert(router.current == "login" and router.history.is_empty())
    router.go("headquarters")
    router.go("settings")
    assert(router.current == "settings" and router.history.size() == 2)
    assert(router.back() and router.current == "headquarters")
    assert(router.back() and router.current == "login")
    assert(not router.back())
    router.go("updates")
    router.reset("login")
    assert(router.history.is_empty())
    var cutout := Safe.margins(Vector2(1280,720),Vector2i(2400,1080),Rect2i(100,0,2300,1080))
    assert(cutout.left >= 65 and cutout.right >= 12)
    assert(Keyboard.visible_canvas_height(Vector2(1280,720),Vector2i(2400,1080),400) < 500.0)
    print("router smoke OK: transitions, back stack, resets, cutout, keyboard")
    quit(0)
