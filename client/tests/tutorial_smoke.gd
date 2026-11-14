extends SceneTree
## Offline onboarding smoke: visibility, real step events, persistence, skip.
func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    var session := get_root().get_node_or_null("GameSession")
    if session == null:
        push_error("TUTORIAL_SMOKE_FAIL GameSession unavailable")
        quit(1)
        return
    var account := "qa_tutorial_%d" % Time.get_ticks_usec()
    session.sign_in("synthetic-smoke-token", account)
    var root: Control = load("res://world.tscn").instantiate()
    get_root().add_child(root)
    await process_frame
    await process_frame
    var tutorial: Control = root.tutorial_panel
    if tutorial == null or not tutorial.visible:
        push_error("TUTORIAL_SMOKE_FAIL fresh account hint missing")
        root.queue_free()
        quit(1)
        return
    assert(tutorial._first_incomplete() == 0)
    tutorial.notify("economy_opened")
    assert(tutorial._first_incomplete() == 0, "unrelated events do not count as farm construction")
    tutorial.notify("farm_built")
    assert(tutorial._first_incomplete() == 2, "only server-confirmed farm event unlocks next hint")
    tutorial.notify("city_opened")
    tutorial.notify("contracts_opened")
    assert(not tutorial.visible, "completed tutorial hides")
    var saved_path: String = tutorial.account_path
    var reopened: Control = load("res://tutorial.gd").new()
    reopened.setup(root, account)
    assert(reopened._first_incomplete() == 4 and not reopened.visible, "state restored per account")
    reopened.queue_free()

    var other_account := account + "_skip"
    var skip_tutorial: Control = load("res://tutorial.gd").new()
    skip_tutorial.setup(root, other_account)
    assert(skip_tutorial.visible, "other account gets independent hints")
    skip_tutorial.skip()
    assert(not skip_tutorial.visible, "skip hides hints")
    var skipped_path: String = skip_tutorial.account_path
    var reopening: Control = load("res://tutorial.gd").new()
    reopening.setup(root, other_account)
    assert(not reopening.visible and reopening.skipped, "skip persisted")
    reopening.queue_free()
    skip_tutorial.queue_free()
    DirAccess.remove_absolute(ProjectSettings.globalize_path(saved_path))
    DirAccess.remove_absolute(ProjectSettings.globalize_path(skipped_path))
    session.sign_out()
    print("TUTORIAL_SMOKE_PASS events/persistence/per-account/skip")
    root.queue_free()
    quit(0)
