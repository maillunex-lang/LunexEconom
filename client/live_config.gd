extends Node
## Signed JSON configuration. Offline cache is re-verified on every load.
signal changed(revision: int)
signal check_finished(message: String, ok: bool)

const API := "https://rikagro.ru/lunexeconom/api/config"
const DIR := "user://live_config/"
const MAX_RESPONSE := 131072
const MAX_PAYLOAD := 65536
const INTERVAL := 600.0

var revision := -1
var settings: Dictionary = {}
var last_error := ""
var public_key_path := "res://livepatch_public.pem"
var url_override := "" # test-only
var busy := false
var timer: Timer

func _ready() -> void:
    load_cache()
    timer = Timer.new()
    timer.wait_time = INTERVAL
    timer.one_shot = false
    timer.autostart = true
    add_child(timer)
    timer.timeout.connect(check_once)
    # Network call is deferred so the initial UI remains responsive.
    call_deferred("check_once")

func _notification(what: int) -> void:
    if what == NOTIFICATION_APPLICATION_RESUMED:
        call_deferred("check_once")

func _key() -> CryptoKey:
    var k := CryptoKey.new()
    if k.load(public_key_path, true) != OK:
        return null
    return k

func verify(raw: PackedByteArray, signature_b64: String) -> bool:
    var key := _key()
    if key == null or raw.is_empty() or raw.size() > MAX_PAYLOAD:
        return false
    if signature_b64.length() < 40 or signature_b64.length() > 2048:
        return false
    var signature := Marshalls.base64_to_raw(signature_b64)
    if signature.is_empty():
        return false
    var hasher := HashingContext.new()
    hasher.start(HashingContext.HASH_SHA256)
    hasher.update(raw)
    return Crypto.new().verify(HashingContext.HASH_SHA256, hasher.finish(), signature, key)

func parse_envelope(data: Variant) -> Dictionary:
    if not data is Dictionary or data.get("schema") != 1:
        return {}
    if not data.get("payload_b64") is String or not data.get("signature") is String:
        return {}
    var raw := Marshalls.base64_to_raw(str(data["payload_b64"]))
    if not verify(raw, str(data["signature"])):
        return {}
    var payload: Variant = JSON.parse_string(raw.get_string_from_utf8())
    if not payload is Dictionary or payload.get("schema") != 1:
        return {}
    var rev: Variant = payload.get("revision", -1)
    if not (typeof(rev) == TYPE_INT or (typeof(rev) == TYPE_FLOAT and rev == floorf(rev))) or int(rev) < 0:
        return {}
    if int(data.get("revision", -1)) != int(rev):
        return {}
    if not payload.get("flags", {}) is Dictionary or not payload.get("texts", {}) is Dictionary or not payload.get("parameters", {}) is Dictionary:
        return {}
    return payload

func use_envelope(data: Variant) -> bool:
    var parsed := parse_envelope(data)
    if parsed.is_empty() or int(parsed["revision"]) < revision:
        return false
    var next_revision := int(parsed["revision"])
    if next_revision == revision:
        return true
    if not _store(data):
        return false
    settings = parsed
    revision = next_revision
    changed.emit(revision)
    return true

func _store(data: Dictionary) -> bool:
    DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(DIR))
    var tmp := DIR + "config.tmp"
    var file := FileAccess.open(tmp, FileAccess.WRITE)
    if file == null:
        return false
    file.store_string(JSON.stringify(data))
    file.close()
    return DirAccess.rename_absolute(ProjectSettings.globalize_path(tmp),
        ProjectSettings.globalize_path(DIR + "config.json")) == OK

func load_cache() -> bool:
    if not FileAccess.file_exists(DIR + "config.json"):
        return false
    var data: Variant = JSON.parse_string(FileAccess.get_file_as_string(DIR + "config.json"))
    var parsed := parse_envelope(data)
    if parsed.is_empty():
        return false
    settings = parsed
    revision = int(parsed["revision"])
    changed.emit(revision)
    return true

func visible(name: String, default_value: bool = true) -> bool:
    return bool(settings.get("flags", {}).get(name, default_value))

func override_text(name: String, default_value: String) -> String:
    return str(settings.get("texts", {}).get(name, default_value))

func check_once() -> void:
    if busy:
        check_finished.emit("Проверка конфигурации уже выполняется", false)
        return
    busy = true
    var req := HTTPRequest.new()
    req.timeout = 12
    req.body_size_limit = MAX_RESPONSE
    add_child(req)
    var endpoint := url_override if not url_override.is_empty() else API
    var err := req.request(endpoint)
    if err != OK:
        req.queue_free()
        busy = false
        last_error = "Не удалось подключиться к серверу конфигурации"
        check_finished.emit(last_error, false)
        return
    var res: Array = await req.request_completed
    req.queue_free()
    busy = false
    if res[0] != HTTPRequest.RESULT_SUCCESS or res[1] != 200:
        last_error = "Ошибка сети. Используется сохранённая конфигурация"
        check_finished.emit(last_error, false)
        return
    var envelope: Variant = JSON.parse_string((res[3] as PackedByteArray).get_string_from_utf8())
    if not use_envelope(envelope):
        last_error = "Подпись конфигурации неверна или получена устаревшая версия"
        check_finished.emit(last_error, false)
        return
    last_error = ""
    check_finished.emit("Конфигурация актуальна: ревизия %d" % revision, true)
