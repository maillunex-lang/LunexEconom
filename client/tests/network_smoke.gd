extends SceneTree
const PublicBase = preload("res://config/public_base.gd")
const ManifestClient = preload("res://update/manifest_client.gd")
const Downloader = preload("res://update/resumable_download.gd")
const UpdateManager = preload("res://update/update_manager.gd")

var manifest_result: Dictionary = {}
var failed_reason := ""
var download_path := ""
var download_error := ""

func _initialize() -> void:
    call_deferred("_run")

func _failed(_kind: String, why: String) -> void:
    failed_reason = why

func _loaded(_kind: String, data: Dictionary) -> void:
    manifest_result = data

func _download_finished(path: String) -> void:
    download_path = path

func _download_failed(reason: String) -> void:
    download_error = reason

func _run() -> void:
    var args := OS.get_cmdline_user_args()
    if args.size() != 7:
        printerr("Expected: base pubkey cert apk_sha apk_size pack_sha pack_size")
        quit(20)
        return
    PublicBase.default_base_url = args[0]
    var cert := X509Certificate.new()
    if cert.load(args[2]) != OK:
        printerr("Cannot load trusted test CA")
        quit(21)
        return
    var tls := TLSOptions.client(cert)
    var fetcher := ManifestClient.new()
    fetcher.public_key_path = args[1]
    fetcher.tls_options = tls
    root.add_child(fetcher)
    fetcher.loaded.connect(_loaded)
    fetcher.failed.connect(_failed)
    fetcher.fetch("update")
    for i in range(100):
        if not manifest_result.is_empty() or not failed_reason.is_empty():
            break
        await create_timer(0.1).timeout
    if manifest_result.is_empty():
        printerr("Manifest fetch failed: " + failed_reason)
        quit(22)
        return
    var manager := UpdateManager.new()
    # A client at N sees a signed N+1 manifest, without a forced upgrade.
    manager.current_version_code = int(manifest_result["version_code"]) - 1
    manager.manifest = manifest_result
    if int(manifest_result["version_code"]) != manager.current_version_code + 1:
        printerr("Signed update is not N+1")
        quit(30)
        return
    if manager._mandatory():
        printerr("The previous version should receive an optional update")
        quit(31)
        return
    # Older versions must be blocked when min_version_code exceeds their code.
    manager.current_version_code = 1
    if not manager._mandatory():
        printerr("min_version_code must block old clients")
        quit(23)
        return

    # Any signed payload with foreign host or bad sha256 must fail validation.
    var invalid_host := manifest_result.duplicate(true)
    invalid_host["apk_url"] = "https://evil.invalid/download/lunex.apk"
    if preload("res://update/manifest_verifier.gd").valid_update(invalid_host):
        printerr("Foreign APK host accepted")
        quit(32)
        return
    # The fake server deliberately tampers with content.json but reuses its signature.
    manifest_result.clear()
    failed_reason = ""
    fetcher.fetch("content")
    for i in range(100):
        if not manifest_result.is_empty() or not failed_reason.is_empty():
            break
        await create_timer(0.1).timeout
    if failed_reason.is_empty():
        printerr("Tampered content manifest was not rejected")
        quit(24)
        return

    var downloader := Downloader.new()
    downloader.tls_options = tls
    root.add_child(downloader)
    downloader.finished.connect(_download_finished)
    downloader.failed.connect(_download_failed)
    var expected_size := int(args[4])
    var apk_url := PublicBase.url("download/lunex.apk")
    var target := "user://updates/network-fixture.apk"
    DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path("user://updates"))
    var part := target + "." + args[3] + ".part"
    var partial := FileAccess.open(part, FileAccess.WRITE)
    partial.store_buffer("LUNEX-".to_utf8_buffer())
    partial.close()

    downloader.download(apk_url, target, expected_size, args[3])
    for i in range(200):
        if not download_path.is_empty() or not download_error.is_empty():
            break
        await create_timer(0.1).timeout
    if download_path.is_empty():
        printerr("Download failed: " + download_error)
        quit(25)
        return
    if FileAccess.get_sha256(target) != args[3]:
        printerr("Bad APK SHA after resumed download")
        quit(26)
        return

    download_path = ""
    download_error = ""
    downloader.download(apk_url, "user://updates/invalid.apk", expected_size, "f".repeat(64))
    for i in range(150):
        if not download_path.is_empty() or not download_error.is_empty():
            break
        await create_timer(0.1).timeout
    if download_error.is_empty() or FileAccess.file_exists("user://updates/invalid.apk"):
        printerr("Bad SHA was not rejected and deleted")
        quit(27)
        return

    download_path = ""
    download_error = ""
    var pack_target := "user://packs/core_start-1.0.0.pck"
    downloader.download(PublicBase.url("packs/core_start-1.0.0.pck"), pack_target, int(args[6]), args[5])
    for i in range(150):
        if not download_path.is_empty() or not download_error.is_empty():
            break
        await create_timer(0.1).timeout
    if download_path.is_empty() or not ProjectSettings.load_resource_pack(ProjectSettings.globalize_path(pack_target), false):
        printerr("Pack download/mount failed: " + download_error)
        quit(28)
        return
    var image = load("res://content/core_start/icon.png")
    if image == null:
        printerr("Downloaded PCK image unavailable without restart")
        quit(29)
        return
    print("HTTPS fake-server smoke OK: signed/tampered manifest, mandatory version, interrupted resume, invalid SHA, PCK live mount")
    quit(0)
