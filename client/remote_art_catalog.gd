extends Node
## Optional licensed art catalog, SHA-256 verified and cached after APK installation.
signal updated
const MANIFEST_URL := "https://rikagro.ru/lunexeconom/assets/art-catalog/manifest.json"
const ASSET_ROOT := "https://rikagro.ru/lunexeconom/assets/art-catalog/"
const CACHE := "user://catalog_art/"
const MAX_IMAGE_BYTES := 8 * 1024 * 1024
var _request: HTTPRequest
var _items: Array = []
var _index: int = -1
var _textures: Dictionary = {}
var _busy := false

func _ready() -> void:
    _request = HTTPRequest.new()
    _request.timeout = 18.0
    _request.body_size_limit = MAX_IMAGE_BYTES
    add_child(_request)
    _request.request_completed.connect(_completed)
    refresh()

func refresh() -> void:
    if _busy:
        return
    _busy = true
    _index = -1
    if _request.request(MANIFEST_URL) != OK:
        _busy = false

func texture_for(art_id: String) -> Texture2D:
    return _textures.get(art_id, null)

func _completed(result: int, status: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
    if _index == -1:
        if result != HTTPRequest.RESULT_SUCCESS or status != 200:
            _busy = false
            return
        var parsed = JSON.parse_string(body.get_string_from_utf8())
        if not parsed is Dictionary or not parsed.get("files") is Array:
            _busy = false
            return
        _items.clear()
        for item in parsed["files"]:
            if not item is Dictionary:
                continue
            var art_id := str(item.get("id", ""))
            var sha := str(item.get("sha256", ""))
            var url := str(item.get("url", ""))
            if art_id.length() > 80 or not art_id.contains("."):
                continue
            if sha.length() != 64 or not sha.is_valid_hex_number():
                continue
            if not url.begins_with("/lunexeconom/assets/art-catalog/"):
                continue
            if not url.ends_with("/" + sha + ".png"):
                continue
            _items.append({"id": art_id, "sha": sha, "url": url})
        _index = 0
        _next()
        return
    if _index >= _items.size():
        _busy = false
        return
    var item: Dictionary = _items[_index]
    if result == HTTPRequest.RESULT_SUCCESS and status == 200 and body.size() <= MAX_IMAGE_BYTES:
        var context := HashingContext.new()
        context.start(HashingContext.HASH_SHA256)
        context.update(body)
        if context.finish().hex_encode() == item["sha"]:
            var img := Image.new()
            if img.load_png_from_buffer(body) == OK:
                DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(CACHE))
                var filename: String = CACHE + str(item["sha"]) + ".png"
                var file := FileAccess.open(filename + ".tmp", FileAccess.WRITE)
                if file != null:
                    file.store_buffer(body)
                    file.close()
                    if DirAccess.rename_absolute(ProjectSettings.globalize_path(filename + ".tmp"), ProjectSettings.globalize_path(filename)) == OK:
                        _textures[item["id"]] = ImageTexture.create_from_image(img)
                        updated.emit()
    _index += 1
    _next()

func _next() -> void:
    while _index < _items.size():
        var item: Dictionary = _items[_index]
        var cached: String = CACHE + str(item["sha"]) + ".png"
        if FileAccess.file_exists(cached) and FileAccess.get_sha256(cached) == item["sha"]:
            var img := Image.new()
            if img.load(ProjectSettings.globalize_path(cached)) == OK:
                _textures[item["id"]] = ImageTexture.create_from_image(img)
                updated.emit()
                _index += 1
                continue
        var url: String = "https://rikagro.ru" + str(item["url"])
        if not url.begins_with(ASSET_ROOT):
            _index += 1
            continue
        if _request.request(url) == OK:
            return
        _index += 1
    _busy = false