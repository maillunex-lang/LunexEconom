extends SceneTree

func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    var scene := load("res://main.tscn")
    assert(scene != null)
    var instance: Node = scene.instantiate()
    root.add_child(instance)
    await process_frame
    await process_frame
    assert(instance.get("form") != null)
    assert(instance.get("headquarters") != null)
    assert(instance.get("login_email") != null)
    assert(instance.get_node_or_null("PresenceTimer") != null)
    assert(not instance.get("headquarters").visible)
    assert(DisplayServer.window_get_size().x >= DisplayServer.window_get_size().y)
    instance._save_refresh("device-test-only")
    assert(instance._load_refresh() == "device-test-only")
    instance._clear_tokens()
    assert(instance._load_refresh().is_empty())
    var crypto := Crypto.new()
    var key := crypto.generate_rsa(2048)
    assert(key != null)
    var data: PackedByteArray = '{"a":1,"z":2}'.to_utf8_buffer()
    var hasher := HashingContext.new()
    assert(hasher.start(HashingContext.HASH_SHA256) == OK)
    assert(hasher.update(data) == OK)
    var sha: PackedByteArray = hasher.finish()
    var signature: PackedByteArray = crypto.sign(HashingContext.HASH_SHA256,sha,key)
    var config := {"schema":1,"revision":7,"payload_b64":Marshalls.raw_to_base64(data),"signature":Marshalls.raw_to_base64(signature)}
    assert(instance._verify_signed_config(config,key.save_to_string(true)))
    config["payload_b64"] = Marshalls.raw_to_base64('{"a":2,"z":2}'.to_utf8_buffer())
    assert(not instance._verify_signed_config(config,key.save_to_string(true)))
    var fixture: Variant = JSON.parse_string(FileAccess.get_file_as_string("res://tests/config_signed_fixture.json"))
    assert(fixture is Dictionary)
    assert(instance._verify_signed_config(fixture))
    print("V2.1 client smoke OK: login, email, refresh storage, HQ, RSA verify, landscape")
    quit(0)
