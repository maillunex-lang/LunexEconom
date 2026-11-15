extends Node
## Android-only test updater. Manifest and payload must be served over the pinned HTTPS origin.
signal state_changed(message: String, can_install: bool)
const MANIFEST_URL := "https://rikagro.ru/lunexeconom/updates/manifest.json"
const BASE_URL := "https://rikagro.ru/lunexeconom/versions/"
## Installed build number: CI stamps it into res://build_info.json (ops/stamp_build.py) together with the export preset.
var local_version := _read_local_version()
const MAX_APK_BYTES := 160 * 1024 * 1024
const MAX_CONTENT_BYTES := 2 * 1024 * 1024
var manifest: Dictionary = {}
var downloaded_apk := ""
var busy := false

func _read_local_version() -> int:
    var file := FileAccess.open("res://build_info.json", FileAccess.READ)
    if file == null: return 0
    var data = JSON.parse_string(file.get_as_text())
    return int(data.get("version_code", 0)) if data is Dictionary else 0

func check() -> void:
    if busy: return
    # A failed refresh must not be mistaken for a fresh successful check.
    manifest.clear()
    busy = true
    state_changed.emit("Проверяем обновления...", false)
    var req := HTTPRequest.new()
    req.timeout = 12
    add_child(req)
    req.request_completed.connect(func(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
        req.queue_free()
        busy = false
        if result != HTTPRequest.RESULT_SUCCESS or code != 200 or body.size() > 65536:
            state_changed.emit("Не удалось проверить обновления", false)
            return
        var data = JSON.parse_string(body.get_string_from_utf8())
        if not _valid_manifest(data):
            state_changed.emit("Неверные данные обновления", false)
            return
        manifest = data
        _check_content()
        var apk: Dictionary = manifest["apk"]
        if int(apk["version_code"]) > local_version:
            state_changed.emit("Доступна версия %s. Нажмите «Обновить»." % str(apk["version_name"]), false)
        else:
            state_changed.emit("Версия актуальна · %s" % str(apk["version_name"]), false)
    )
    var err := req.request(MANIFEST_URL, [], HTTPClient.METHOD_GET)
    if err != OK:
        busy = false
        req.queue_free()
        state_changed.emit("Ошибка сети", false)

func _valid_payload(item: Variant, max_bytes: int) -> bool:
    if not item is Dictionary: return false
    if not item.get("url", "") is String or not str(item.get("url", "")).begins_with(BASE_URL): return false
    if "?" in str(item["url"]) or "#" in str(item["url"]): return false
    var name := str(item["url"]).trim_prefix(BASE_URL)
    if name.is_empty() or "/" in name or ".." in name: return false
    var hash_value := str(item.get("sha256", ""))
    if hash_value.length() != 64 or not hash_value.is_valid_hex_number(): return false
    var length := int(item.get("size", 0))
    return length > 0 and length <= max_bytes

func _valid_manifest(data: Variant) -> bool:
    if not data is Dictionary or int(data.get("schema", 0)) != 1: return false
    if not data.has("apk") or not _valid_payload(data["apk"], MAX_APK_BYTES): return false
    if not str(data["apk"]["url"]).ends_with(".apk"): return false
    if int(data["apk"].get("version_code", 0)) < 1: return false
    if data.has("content") and not _valid_payload(data["content"], MAX_CONTENT_BYTES): return false
    if data.has("content") and not str(data["content"]["url"]).ends_with(".json"): return false
    return true

func download_apk() -> void:
    if busy or manifest.is_empty(): return
    var apk: Dictionary = manifest["apk"]
    if int(apk["version_code"]) <= local_version:
        state_changed.emit("Установлена актуальная версия", false)
        return
    busy = true
    state_changed.emit("Загружаем APK...", false)
    var req := HTTPRequest.new()
    req.timeout = 90
    req.download_file = "user://update.tmp.apk"
    req.body_size_limit = MAX_APK_BYTES
    add_child(req)
    req.request_completed.connect(func(result: int, code: int, _headers: PackedStringArray, _body: PackedByteArray) -> void:
        req.queue_free()
        busy = false
        var path := ProjectSettings.globalize_path("user://update.tmp.apk")
        if result != HTTPRequest.RESULT_SUCCESS or code != 200 or not FileAccess.file_exists(path):
            state_changed.emit("Ошибка загрузки APK", false)
            return
        var expected := str(apk["sha256"]).to_lower()
        var actual := FileAccess.get_sha256(path).to_lower()
        var f := FileAccess.open(path, FileAccess.READ)
        var length := f.get_length() if f else 0
        if length != int(apk["size"]) or actual != expected:
            DirAccess.remove_absolute(path)
            state_changed.emit("Проверка APK не пройдена. Файл удалён", false)
            return
        downloaded_apk = path
        state_changed.emit("APK проверена. Нажмите «Установить».", true)
    )
    var err := req.request(str(apk["url"]))
    if err != OK:
        busy = false
        req.queue_free()
        state_changed.emit("Не удалось начать загрузку", false)

func install_apk() -> void:
    if downloaded_apk.is_empty() or not FileAccess.file_exists(downloaded_apk): return
    if not OS.has_feature("android"):
        state_changed.emit("Установка доступна только на Android", true)
        return
    var runtime = JavaClassWrapper.wrap("org.godotengine.godot.utils.GodotAndroidRuntime")
    var activity = runtime.getActivity()
    if activity == null:
        state_changed.emit("Системный установщик недоступен", true)
        return
    var file_class = JavaClassWrapper.wrap("java.io.File")
    var file_obj = file_class.new(downloaded_apk)
    var provider = JavaClassWrapper.wrap("androidx.core.content.FileProvider")
    var uri = provider.getUriForFile(activity, "ru.lunex.bashkiriahoneyoil.fileprovider", file_obj)
    var intent_class = JavaClassWrapper.wrap("android.content.Intent")
    var intent = intent_class.new("android.intent.action.VIEW")
    intent.setDataAndType(uri, "application/vnd.android.package-archive")
    intent.addFlags(1)
    intent.addFlags(268435456)
    activity.startActivity(intent)
    state_changed.emit("Подтвердите установку в Android", true)

func _check_content() -> void:
    if not manifest.has("content"): return
    var content: Dictionary = manifest["content"]
    var req := HTTPRequest.new()
    req.timeout = 12
    req.body_size_limit = MAX_CONTENT_BYTES
    add_child(req)
    req.request_completed.connect(func(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
        req.queue_free()
        if result != HTTPRequest.RESULT_SUCCESS or code != 200 or body.size() != int(content["size"]): return
        var digest := HashingContext.new()
        digest.start(HashingContext.HASH_SHA256)
        digest.update(body)
        if digest.finish().hex_encode().to_lower() != str(content["sha256"]).to_lower(): return
        var data = JSON.parse_string(body.get_string_from_utf8())
        if not data is Dictionary or int(data.get("schema", 0)) != 1: return
        # Content is inert, validated data; never load scripts, packed scenes or executable resources.
        var f := FileAccess.open("user://verified_content.json", FileAccess.WRITE)
        if f: f.store_buffer(body)
    )
    req.request(str(content["url"]))