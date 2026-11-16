extends SceneTree
const Mock = preload("res://tests/onboarding_mock.gd")
const SCREENS_WITH_NAV := ["headquarters","map","enterprises","settings","more","finance"]
const SCREENS_WITHOUT_NAV := ["login","build","supply","store","updates"]

func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    var app: Control = load("res://main.tscn").instantiate()
    root.add_child(app)
    await process_frame
    await process_frame
    var mock := Mock.new()
    root.add_child(mock)
    app.map_screen.api.mock = Callable(mock,"respond")
    for screen in SCREENS_WITH_NAV:
        app.router.go(screen)
        await process_frame
        assert(app.navigation_bar.visible, "nav absent on " + screen)
        assert(app.navigation_bar.buttons.size()==5)
        for button in app.navigation_bar.buttons.values():
            assert(button.custom_minimum_size.y>=48)
        assert(app.router.host.offset_bottom<0, "nav overlays content on " + screen)
    for screen in SCREENS_WITHOUT_NAV:
        app.router.go(screen)
        await process_frame
        assert(not app.navigation_bar.visible, "nav unexpectedly present on " + screen)
        assert(app.router.host.offset_bottom==0, "hidden nav must not steal space")
    app.router.reset("headquarters")
    var old_history: int = app.router.history.size()
    app.navigation_bar.target_requested.emit("settings")
    await process_frame
    assert(app.router.current=="settings" and app.router.history.size()==old_history+1)
    assert(app.router.back() and app.router.current=="headquarters", "history not preserved")
    app.navigation_bar.focus_tutorial(2)
    assert(app.navigation_bar.buttons["map"].self_modulate != Color.WHITE)
    app.navigation_bar.focus_tutorial(-1)
    assert(app.navigation_bar.buttons["map"].self_modulate == Color.WHITE)
    print("onboarding navigation OK: visibility, 48dp, layout reservation, history, highlighting")
    app.queue_free()
    quit(0)