extends SceneTree
func _initialize() -> void:
    var updater = load("res://updater.gd").new()
    var payload = {"url": "https://rikagro.ru/lunexeconom/versions/test.apk", "sha256": "a".repeat(64), "size": 200}
    assert(updater._valid_payload(payload, 500))
    assert(not updater._valid_payload(payload, 100))
    payload["url"] = "https://evil.example/versions/test.apk"
    assert(not updater._valid_payload(payload, 500))
    payload["url"] = "https://rikagro.ru/lunexeconom/versions/../test.apk"
    assert(not updater._valid_payload(payload, 500))
    payload["url"] = "https://rikagro.ru/lunexeconom/versions/test.apk"
    payload["sha256"] = "broken"
    assert(not updater._valid_payload(payload, 500))
    payload["sha256"] = "a".repeat(64)
    assert(updater._valid_manifest({"schema":1,"apk":{"url":payload["url"],"sha256":payload["sha256"],"size":200,"version_code":4}}))
    assert(not updater._valid_manifest({"schema":2,"apk":payload}))
    print("UPDATER_SMOKE_PASS origin/size/hash/schema/version")
    quit()