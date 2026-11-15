extends SceneTree
var failures := 0
func _initialize() -> void:
    call_deferred("_run")
func test(value: bool, label: String) -> void:
    if not value:
        failures += 1
        print("FAIL ", label)
func _run() -> void:
    var path: String = OS.get_user_data_dir()
    var key: String = path + "/lc_test_private.pem"
    var pub: String = path + "/lc_test_public.pem"
    var other: String = path + "/lc_test_other.pem"
    var output: Array = []
    if OS.execute("openssl", ["genrsa", "-out", key, "2048"], output, true) != 0:
        print("LIVE_CONFIG_SMOKE_SKIP"); quit(0); return
    OS.execute("openssl", ["rsa", "-in", key, "-pubout", "-out", pub], output, true)
    OS.execute("openssl", ["genrsa", "-out", other, "2048"], output, true)
    var config = load("res://live_config.gd").new()
    config.public_key_path = pub
    get_root().add_child(config)
    config.timer.stop()
    var payload := {"schema":1,"revision":7,"flags":{"client_feature_hq":false,"unknown_future_flag":true},
       "parameters":{"future":12},"texts":{"hq_title":"Штаб"},"unknown_payload_field":true}
    var raw: PackedByteArray = JSON.stringify(payload).to_utf8_buffer()
    var input := path + "/lc_payload"
    var sigpath := path + "/lc_sig"
    var f := FileAccess.open(input, FileAccess.WRITE); f.store_buffer(raw); f.close()
    OS.execute("openssl", ["dgst", "-sha256", "-sign", key, "-out", sigpath, input], output, true)
    var signature := Marshalls.raw_to_base64(FileAccess.get_file_as_bytes(sigpath))
    var good := {"schema":1,"revision":7,"payload_b64":Marshalls.raw_to_base64(raw),"signature":signature}
    test(config.parse_envelope(good).get("revision",-1) == 7, "valid signature")
    test(config.use_envelope(good), "save verified config")
    test(not config.visible("client_feature_hq"), "feature visibility")
    test(config.override_text("hq_title","Old") == "Штаб", "texts")
    test(config.load_cache(), "load verified cache")
    var changed: Dictionary = good.duplicate(true)
    changed["revision"] = 8
    test(config.parse_envelope(changed).is_empty(), "outer revision rejected")
    changed = good.duplicate(true)
    changed["payload_b64"] = Marshalls.raw_to_base64(JSON.stringify({"schema":1,"revision":99}).to_utf8_buffer())
    test(config.parse_envelope(changed).is_empty(), "tampered payload rejected")
    changed = good.duplicate(true)
    changed["signature"] = "bm90IGEgc2lnbmF0dXJl"
    test(config.parse_envelope(changed).is_empty(), "wrong signature rejected")
    test(config.visible("new_future_toggle",true), "unknown fields tolerated")
    test(config.revision == 7, "failed signatures leave cache unchanged")
    config.queue_free()
    if failures == 0: print("LIVE_CONFIG_SMOKE_PASS")
    quit(1 if failures else 0)
