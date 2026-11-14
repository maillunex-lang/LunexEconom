extends Node
## Download optional original art after APK installation; keep last verified files.
signal progress(done: int, total: int)
signal finished(ok: bool)
const MANIFEST_URL := "https://rikagro.ru/lunexeconom/assets/manifest.json"
const ROOT := "user://downloaded_art/"
const ALLOWED := ["grocery_1x1.png", "house_panel_a_1x1.png", "house_panel_b_1x1.png", "house_stalinka_2x1.png", "road_asphalt_1x1.png"]
var _request: HTTPRequest
var _files: Array = []
var _index := 0
var _failed := false
var _busy := false

func _ready() -> void:
    _request = HTTPRequest.new()
    _request.timeout = 20.0
    add_child(_request)
    _request.request_completed.connect(_completed)

func start() -> void:
    if _busy: return
    _busy = true
    _failed = false
    _index = 0
    _files.clear()
    var err := _request.request(MANIFEST_URL)
    if err != OK:
        _busy = false
        finished.emit(false)

func _completed(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
    if result != HTTPRequest.RESULT_SUCCESS or code != 200:
        _failed = true
        _next()
        return
    if _files.is_empty() and _index == 0:
        var data = JSON.parse_string(body.get_string_from_utf8())
        if not data is Dictionary or not data.get("files") is Array:
            _busy = false
            finished.emit(false)
            return
        for item in data["files"]:
            if not item is Dictionary: continue
            var name := str(item.get("name", ""))
            var sha := str(item.get("sha256", "")).to_lower()
            if name not in ALLOWED or sha.length() != 64 or not sha.is_valid_hex_number(): continue
            _files.append({"name": name, "sha256": sha})
        _next()
        return
    var item: Dictionary = _files[_index]
    var actual := body.sha256_text()
    if actual != item["sha256"]:
        _failed = true
    else:
        DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(ROOT))
        var target := ROOT + str(item["name"])
        var file := FileAccess.open(target + ".tmp", FileAccess.WRITE)
        if file == null:
            _failed = true
        else:
            file.store_buffer(body)
            file.close()
            var global_temp := ProjectSettings.globalize_path(target + ".tmp")
            var global_target := ProjectSettings.globalize_path(target)
            if DirAccess.rename_absolute(global_temp, global_target) != OK:
                _failed = true
    _index += 1
    progress.emit(_index, _files.size())
    _next()

func _next() -> void:
    if _files.is_empty() or _index >= _files.size():
        _busy = false
        finished.emit(not _failed and not _files.is_empty())
        return
    var item: Dictionary = _files[_index]
    var target := ROOT + str(item["name"])
    if FileAccess.file_exists(target):
        var existing := FileAccess.get_sha256(target)
        if existing == item["sha256"]:
            _index += 1
            progress.emit(_index, _files.size())
            _next()
            return
    var url := "https://rikagro.ru/lunexeconom/assets/" + str(item["name"])
    var err := _request.request(url)
    if err != OK:
        _failed = true
        _index += 1
        _next()
