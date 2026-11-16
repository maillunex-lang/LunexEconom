extends SceneTree
const Login = preload("res://screens/login.tscn")
const URLs = preload("res://config/consent_urls.gd")
const Strings = preload("res://i18n/strings.gd")
func _initialize() -> void:
    call_deferred("_run")
func _run() -> void:
    var view = Login.instantiate()
    root.add_child(view)
    await process_frame
    view.set_mode("register")
    assert(view.consent_checkbox.visible)
    assert(not view.consent_checkbox.button_pressed)
    assert(view.action.disabled)
    assert(view.consent_links.visible)
    view.consent_checkbox.button_pressed = true
    assert(not view.action.disabled)
    view.set_mode("login")
    assert(not view.consent_checkbox.visible)
    assert(not view.action.disabled)
    assert(not view.consent_links.visible)
    assert(URLs.url("policy").is_empty())
    assert(URLs.url("terms").is_empty())
    assert(Strings.has_key("auth.consent.required"))
    assert(Strings.has_key("account.delete.scheduled"))
    view.queue_free()
    print("consent smoke OK")
    quit(0)
