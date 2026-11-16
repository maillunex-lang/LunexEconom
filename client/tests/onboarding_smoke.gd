extends SceneTree
const Mock = preload("res://tests/onboarding_mock.gd")
const Adapter = preload("res://world/api.gd")
const Build = preload("res://screens/build.tscn")
const State = preload("res://tutorial/state.gd")
const Service = preload("res://tutorial/service.gd")
const Words = preload("res://enterprises/strings.gd")

func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    var mock := Mock.new()
    root.add_child(mock)
    var api := Adapter.new()
    root.add_child(api)
    api.mock = Callable(mock, "respond")
    var build := Build.instantiate()
    root.add_child(build)
    build.open(api, {"px":2,"py":0,"zone":"free","site_cells":[]}, Vector2i(14,3))
    for i in range(50):
        await process_frame
        if build.rows.get_child_count() > 0:
            break
    assert(build.rows.get_child_count() > 0, "building choices not loaded")
    var field: Dictionary = mock.BUILDING_CATALOG[0]
    build._choose(field, {"x":14,"y":3})
    await create_timer(0.38).timeout
    await process_frame
    assert(mock.plan_calls == 1, "plan was not called once")
    assert(build.plan_data.get("ok", false))
    assert(build.preview_canvas.road_preview.size() == 2)
    assert(build.plan_details.text.contains("47 000 ₽"))
    assert(build.plan_details.text.contains("2 000 ₽"))
    build.confirmation.hide()
    mock.plan_mode = "money"
    build._choose(field, {"x":14,"y":3})
    await create_timer(0.38).timeout
    await process_frame
    assert(build.plan_shortfall.text.contains("7 000 ₽"), "shortfall not shown")
    assert(not build.confirmation.visible, "insufficient funds must not open confirmation")
    mock.plan_mode = "far"
    build._choose(field, {"x":14,"y":3})
    await create_timer(0.38).timeout
    await process_frame
    assert(build.plan_details.text.contains("12 клеток"), "road_unreachable Russian error missing")
    assert(build.preview_canvas.road_preview.is_empty())
    mock.plan_mode = "ok"
    var previous := mock.plan_calls
    build._choose(field, {"x":12,"y":0})
    build._choose(field, {"x":14,"y":3})
    await create_timer(0.38).timeout
    await process_frame
    assert(mock.plan_calls == previous + 1, "rapid selections must debounce")
    mock.fail_purchase = true
    build.confirmation.hide()
    await build._purchase()
    assert(build.message.text.contains("7 000 ₽"))
    assert(build.message.text.contains("2 000 ₽"))

    var state := State.new()
    state.use_account(mock.mock_account)
    state.reset_progress()
    assert(State.verified_progress({}) == 0)
    var tutorial := Service.new()
    root.add_child(tutorial)
    tutorial.configure(api, mock.mock_account)
    api.set_meta("tutorial_chunks", [Vector2i.ZERO])
    var verified := {"step":-1}
    tutorial.verified.connect(func(step: int): verified["step"] = step)
    await tutorial.refresh()
    assert(verified.step == 2, "start from zero should ask to buy land")
    mock.has_land = true
    await tutorial.refresh()
    assert(verified.step == 3, "land should lead to field step")
    mock.has_field = true
    await tutorial.refresh()
    assert(verified.step == 4, "existing completed field should skip build step")
    state.accept_verified(verified.step)
    assert(state.persist())
    var loaded := State.new()
    loaded.use_account(mock.mock_account)
    assert(loaded.step == 4 and not loaded.completed)
    assert(not loaded.can_skip(), "skip must be disabled")
    loaded.reset_progress()
    var reset := State.new()
    reset.use_account(mock.mock_account)
    assert(reset.step == 0, "reset must persist")
    print("onboarding smoke OK: auto-road plans, money, unreachable, debounce, 409, tutorial server state and persistence")
    quit(0)
