extends Node
## Load verified resource packs after atomic download, fallback to procedural assets.
signal status(message: String)
signal pack_ready(name: String)
signal download_progress(received: int, total: int)
const ManifestClient = preload("res://update/manifest_client.gd")
const Downloader = preload("res://update/resumable_download.gd")
const MAX_CACHE_BYTES := 500 * 1024 * 1024
var fetcher: Node
var downloader: Node
var index: Dictionary = {}
var pending: Array = []
var busy := false
var wifi_only := false
var current_version_code := 1
var _last_input_ms := 0

func _ready() -> void:
    fetcher = ManifestClient.new()
    add_child(fetcher)
    fetcher.loaded.connect(_on_manifest)
    fetcher.failed.connect(func(_kind: String, reason: String): status.emit(reason))
    downloader = Downloader.new()
    add_child(downloader)
    downloader.progress.connect(func(n: int, t: int): download_progress.emit(n, t))
    downloader.finished.connect(_on_downloaded)
    downloader.failed.connect(func(reason: String):
        busy = false
        status.emit(reason)
    )
    current_version_code = _read_version_code()
    _last_input_ms = Time.get_ticks_msec()
    call_deferred("refresh")

func _read_version_code() -> int:
    if not FileAccess.file_exists("res://build_info.json"):
        return 1
    var data = JSON.parse_string(FileAccess.get_file_as_string("res://build_info.json"))
    return int(data.get("version_code", 1)) if data is Dictionary else 1

func _input(_event: InputEvent) -> void:
    _last_input_ms = Time.get_ticks_msec()

func _process(_delta: float) -> void:
    if not busy and not pending.is_empty() and Time.get_ticks_msec() - _last_input_ms > 5000:
        _next_pack()

func refresh() -> void:
    fetcher.fetch("content")

func _on_manifest(kind: String, data: Dictionary) -> void:
    if kind != "content":
        return
    pending.clear()
    for pack in data["packs"]:
        if int(pack["min_version_code"]) <= current_version_code:
            pending.append(pack)
    pending.sort_custom(func(a: Dictionary, b: Dictionary): return a["priority"] == "required" and b["priority"] != "required")
    _next_pack()

func _next_pack() -> void:
    if busy or pending.is_empty():
        return
    if str(pending[0]["priority"]) == "background" and Time.get_ticks_msec() - _last_input_ms < 5000:
        return
    var entry: Dictionary = pending.pop_front()
    for dependency in entry.get("dependencies", []):
        if not _ready_dependency(str(dependency)):
            pending.push_back(entry)
            return
    var target := "user://packs/%s-%s.pck" % [entry["name"], entry["version"]]
    if FileAccess.file_exists(target) and FileAccess.get_sha256(target).to_lower() == str(entry["sha256"]):
        if ProjectSettings.load_resource_pack(ProjectSettings.globalize_path(target), false):
            pack_ready.emit(str(entry["name"]))
            _cleanup_old_versions(str(entry["name"]), str(entry["version"]))
        _next_pack()
        return
    if not _space_available(int(entry["size"])):
        status.emit("Недостаточно места для ресурсного пакета")
        return
    busy = true
    index = entry
    downloader.download(str(entry["url"]), target, int(entry["size"]), str(entry["sha256"]), wifi_only)

func _on_downloaded(path: String) -> void:
    busy = false
    if ProjectSettings.load_resource_pack(ProjectSettings.globalize_path(path), false):
        pack_ready.emit(str(index["name"]))
        _cleanup_old_versions(str(index["name"]), str(index["version"]))
        status.emit("Ресурсы загружены: " + str(index["name"]))
    else:
        status.emit("Не удалось подключить пакет")
    _next_pack()

func _space_available(new_size: int) -> bool:
    var used := 0
    var directory := DirAccess.open("user://packs")
    if directory:
        directory.list_dir_begin()
        while true:
            var name := directory.get_next()
            if name.is_empty():
                break
            if name.ends_with(".pck"):
                var file := FileAccess.open("user://packs/" + name, FileAccess.READ)
                if file:
                    used += file.get_length()
        directory.list_dir_end()
    return used + new_size <= MAX_CACHE_BYTES

func _ready_dependency(name: String) -> bool:
    var directory := DirAccess.open("user://packs")
    if directory == null:
        return false
    for item in directory.get_files():
        if item.begins_with(name + "-") and item.ends_with(".pck"):
            return true
    return false

func _cleanup_old_versions(name: String, version: String) -> void:
    var directory := DirAccess.open("user://packs")
    if directory == null:
        return
    var current := name + "-" + version + ".pck"
    for item in directory.get_files():
        if item.begins_with(name + "-") and item.ends_with(".pck") and item != current:
            DirAccess.remove_absolute(ProjectSettings.globalize_path("user://packs/" + item))
