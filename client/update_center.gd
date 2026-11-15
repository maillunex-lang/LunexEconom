extends Node
## One explicit user action checks all three supported update channels.
signal status_changed(message: String)
signal finished(results: Dictionary)
signal install_available

const PATCH = preload("res://livepatch.gd")
const UPDATER = preload("res://updater.gd")
var busy := false
var results: Dictionary = {}
var patch: Node
var updater: Node

func _ready() -> void:
    patch = PATCH.new()
    patch.name = "ContentPatch"
    add_child(patch)
    updater = UPDATER.new()
    updater.name = "ApkUpdater"
    add_child(updater)

static func summarize(data: Dictionary) -> String:
    return "Конфигурация: %s\nКонтент: %s\nAPK: %s" % [
        str(data.get("config", "не проверена")),
        str(data.get("content", "не проверен")),
        str(data.get("apk", "не проверен"))]

func check_all() -> void:
    if busy: return
    busy = true
    results = {"config":"проверяем…", "content":"ожидание", "apk":"ожидание"}
    status_changed.emit(summarize(results))
    # LiveConfig holds verified fallback when the network fails.
    if LiveConfig.busy:
        results["config"] = "уже проверяется · используется подписанный кеш"
    else:
        LiveConfig.check_once()
        var live_result: Array = await LiveConfig.check_finished
        results["config"] = "ревизия %d" % LiveConfig.revision if bool(live_result[1]) else "ошибка: " + str(live_result[0])
    results["content"] = "проверяем…"
    status_changed.emit(summarize(results))
    var old_revision: int = patch.current_revision()
    if not patch.busy:
        var error_state: Array = [""]
        var on_error := func(reason: String) -> void:
            error_state[0] = reason
        patch.patch_failed.connect(on_error, CONNECT_ONE_SHOT)
        patch.check_and_download()
        var deadline: int = Time.get_ticks_msec() + 35000
        while patch.busy and Time.get_ticks_msec() < deadline:
            await get_tree().process_frame
        if patch.patch_failed.is_connected(on_error):
            patch.patch_failed.disconnect(on_error)
        var current: int = patch.current_revision()
        if patch.busy:
            results["content"] = "превышено время ожидания"
        elif not str(error_state[0]).is_empty():
            results["content"] = "ошибка: " + str(error_state[0])
        elif current > old_revision:
            results["content"] = "обновлён до ревизии %d" % current
        else:
            results["content"] = "актуален"
    else:
        results["content"] = "проверка уже выполняется"
    results["apk"] = "проверяем…"
    status_changed.emit(summarize(results))
    if not updater.busy:
        updater.check()
    var limit: int = Time.get_ticks_msec() + 16000
    while updater.busy and Time.get_ticks_msec() < limit:
        await get_tree().process_frame
    if updater.busy:
        results["apk"] = "сервер не ответил"
    elif updater.manifest.is_empty():
        results["apk"] = "ошибка сети или манифеста"
    else:
        var apk: Dictionary = updater.manifest.get("apk", {})
        if int(apk.get("version_code", 0)) > updater.local_version:
            results["apk"] = "доступна версия " + str(apk.get("version_name", apk.get("version_code", "")))
            install_available.emit()
        else:
            results["apk"] = "актуальна"
    busy = false
    status_changed.emit(summarize(results))
    finished.emit(results.duplicate(true))

func install() -> void:
    if updater.downloaded_apk != "":
        updater.install_apk()
    elif not updater.manifest.is_empty():
        updater.download_apk()
