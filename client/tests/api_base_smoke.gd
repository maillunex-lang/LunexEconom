extends SceneTree
const PublicBase = preload("res://config/public_base.gd")
const Adapter = preload("res://world/api.gd")

func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    assert(PublicBase.api_url() == "https://rikagro.ru/lunexeconom/v2/api")
    assert(PublicBase.base_url() == "https://rikagro.ru/lunexeconom/v2")
    ProjectSettings.set_setting("lunex/api_path", "v2/api")
    assert(PublicBase.api_url() == "https://rikagro.ru/lunexeconom/v2/v2/api")
    ProjectSettings.set_setting("lunex/api_path", "api")
    assert(PublicBase.api_url() == "https://rikagro.ru/lunexeconom/v2/api")
    for unsafe in ["", "/api", "api/", "../api", "v2/../api", "http://evil", "https://evil", "api@evil", "api?x", "api#x", "api\\x", "api//x", "api%2fsecret"]:
        ProjectSettings.set_setting("lunex/api_path", unsafe)
        assert(PublicBase.api_url().is_empty(), "Unsafe API path accepted: " + unsafe)
    ProjectSettings.set_setting("lunex/api_path", "api?bad")
    var adapter := Adapter.new()
    root.add_child(adapter)
    var response: Dictionary = await adapter.fetch("/clock")
    assert(response.get("code") == 0)
    assert(response.get("data", {}).get("error") == "service_unavailable")
    adapter.queue_free()
    ProjectSettings.clear("lunex/api_path")
    assert(PublicBase.api_url() == "https://rikagro.ru/lunexeconom/v2/api")
    print("api base smoke OK")
    quit(0)
