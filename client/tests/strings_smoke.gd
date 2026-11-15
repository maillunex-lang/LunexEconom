extends SceneTree
const Strings = preload("res://i18n/strings.gd")
func _initialize() -> void:
    call_deferred("_run")
func _run() -> void:
    var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string("res://data/strings.json"))
    assert(parsed is Dictionary)
    assert(parsed.size() >= 280)
    for key in parsed.keys():
        assert(Strings.has_key(key))
        assert(Strings.get_text(key) == parsed[key])
    assert(Strings.get_text("update.screen.available",{"version":"2.5"}) == "Доступна версия 2.5")
    assert(Strings.get_text("__missing_test_key__") == "__missing_test_key__")
    print("strings smoke OK: ",parsed.size()," Russian keys, substitution, missing key")
    quit(0)
