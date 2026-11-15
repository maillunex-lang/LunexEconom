extends SceneTree
var failures := 0
func _initialize() -> void:
    call_deferred("_run")
func test(value: bool, label: String) -> void:
    if not value:
        failures += 1
        print("FAIL ", label)
func _run() -> void:
    var center: Node = load("res://update_center.gd").new()
    get_root().add_child(center)
    var summary: String = center.summarize({"config":"ревизия 4","content":"актуален","apk":"доступна версия 6"})
    test(summary.contains("ревизия 4"), "configuration result")
    test(summary.contains("Контент: актуален"), "content result")
    test(summary.contains("APK: доступна версия 6"), "apk result")
    test(center.summarize({"config":"ошибка сети"}).contains("ошибка сети"), "network error in Russian")
    test(center.summarize({}).contains("не проверена"), "safe defaults")
    test(center.get_node_or_null("ApkUpdater") != null, "APK updater present")
    test(center.get_node_or_null("ContentPatch") != null, "LivePatch present")
    center.queue_free()
    if failures == 0: print("UPDATE_CENTER_SMOKE_PASS")
    quit(1 if failures else 0)
