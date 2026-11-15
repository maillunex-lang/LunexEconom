extends Node
## UI-independent update state machine; UI-01 should connect to signals.
signal state_changed(message: String, can_install: bool, mandatory: bool)
signal progress(received: int, total: int)
const PublicBase = preload("res://config/public_base.gd")
const ManifestClient = preload("res://update/manifest_client.gd")
const Downloader = preload("res://update/resumable_download.gd")
const CHECK_INTERVAL_SECONDS := 3600
var manifest: Dictionary = {}
var current_version_code := 1
var local_apk := ""
var wifi_only := false
var checking := false
var elapsed := 0.0
var fetcher: Node
var downloader: Node

func _ready() -> void:
    fetcher = ManifestClient.new()
    add_child(fetcher)
    fetcher.loaded.connect(_manifest_loaded)
    fetcher.failed.connect(func(_kind: String, reason: String):
        checking = false
        state_changed.emit(reason, false, _mandatory())
    )
    downloader = Downloader.new()
    add_child(downloader)
    downloader.progress.connect(func(n: int, t: int): progress.emit(n,t))
    downloader.failed.connect(func(reason: String): state_changed.emit(reason, false, _mandatory()))
    downloader.finished.connect(_download_finished)
    current_version_code = _version_code()
    call_deferred("check")

func _process(delta: float) -> void:
    elapsed += delta
    if elapsed >= CHECK_INTERVAL_SECONDS:
        elapsed = 0.0
        check()

func _version_code() -> int:
    if not FileAccess.file_exists("res://build_info.json"):
        return 1
    var parsed = JSON.parse_string(FileAccess.get_file_as_string("res://build_info.json"))
    return int(parsed.get("version_code", 1)) if parsed is Dictionary else 1

func check() -> void:
    if checking or fetcher.busy:
        return
    checking = true
    elapsed = 0
    state_changed.emit("Проверяем обновления...", false, false)
    fetcher.fetch("update")

func _manifest_loaded(kind: String, data: Dictionary) -> void:
    if kind != "update":
        return
    checking = false
    manifest = data
    if int(data["version_code"]) > current_version_code:
        state_changed.emit("Доступно обновление " + str(data["version_name"]), false, _mandatory())
    else:
        state_changed.emit("Установлена актуальная версия", false, false)

func _mandatory() -> bool:
    return not manifest.is_empty() and int(manifest.get("min_version_code", 0)) > current_version_code

func download_apk() -> void:
    if manifest.is_empty() or downloader.busy or int(manifest["version_code"]) <= current_version_code:
        return
    state_changed.emit("Загружаем APK...", false, _mandatory())
    downloader.download(str(manifest["apk_url"]), "user://updates/lunex.apk", int(manifest["size"]), str(manifest["sha256"]), wifi_only)

func _download_finished(path: String) -> void:
    local_apk = path
    state_changed.emit("APK проверен, можно установить", true, _mandatory())

func install() -> void:
    if not FileAccess.file_exists(local_apk):
        state_changed.emit("APK ещё не загружен", false, _mandatory())
        return
    if OS.get_name() != "Android" or not Engine.has_singleton("LunexInstaller"):
        state_changed.emit("Установка доступна только в Android-сборке с плагином", false, _mandatory())
        return
    Engine.get_singleton("LunexInstaller").installApk(ProjectSettings.globalize_path(local_apk))
