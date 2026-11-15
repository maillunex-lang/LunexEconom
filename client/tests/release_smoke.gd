extends SceneTree
const PublicBase = preload("res://config/public_base.gd")
const Verifier = preload("res://update/manifest_verifier.gd")
const ManifestClient = preload("res://update/manifest_client.gd")
const Downloader = preload("res://update/resumable_download.gd")
const UpdateManager = preload("res://update/update_manager.gd")
const ContentManager = preload("res://content/content_manager.gd")

func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    assert(PublicBase.base_url() == "https://rikagro.ru/lunexeconom")
    assert(PublicBase.url("update.json") == "https://rikagro.ru/lunexeconom/update.json")
    assert(not PublicBase.allows_file_url("https://rikagro.ru.evil.io/lunexeconom/x"))
    assert(not PublicBase.allows_file_url("https://rikagro.ru/lunexeconom/../secret"))
    assert(not Verifier.valid_update({}))
    assert(not Verifier.verify("test".to_utf8_buffer(), "invalid"))
    assert(not Downloader.new()._valid_range(PackedStringArray(["Content-Range: bytes 0-3/4"]), 1, 3, 4))
    var manifest := ManifestClient.new()
    var update := UpdateManager.new()
    var content := ContentManager.new()
    assert(update._version_code() >= 1)
    print("release client smoke OK")
    quit(0)
