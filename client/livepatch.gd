extends Node
## Opt-in, data-only patch downloader. Do not autoload until server deployment is reviewed.
signal patch_ready(revision: int)
signal patch_failed(reason: String)

const ORIGIN := "https://rikagro.ru/lunexeconom/admin/patch/"
const MANIFEST := ORIGIN + "manifest.json"
const MAX_MANIFEST := 512 * 1024
const MAX_IMAGE := 8 * 1024 * 1024
const MAX_ASSETS := 300
var busy := false

func _valid_asset(item: Variant) -> bool:
    if not item is Dictionary:
        return false
    var ident := str(item.get("id", ""))
    if ident.length() < 2 or ident.length() > 64:
        return false
    for character in ident:
        if not (character in "abcdefghijklmnopqrstuvwxyz0123456789_-"):
            return false
    var extension := str(item.get("extension", ""))
    if extension != "png" and extension != "webp":
        return false
    var digest := str(item.get("sha256", ""))
    if digest.length() != 64 or not digest.is_valid_hex_number():
        return false
    var size: Variant = item.get("size", 0)
    if typeof(size) != TYPE_INT or size <= 0 or size > MAX_IMAGE:
        return false
    return str(item.get("url", "")) == "blobs/" + digest + "." + extension

func _valid_manifest(data: Variant) -> bool:
    if not data is Dictionary or data.get("schema") != 1:
        return false
    if typeof(data.get("revision")) != TYPE_INT or int(data["revision"]) < 0:
        return false
    if not data.get("assets") is Array or data["assets"].size() > MAX_ASSETS:
        return false
    for asset in data["assets"]:
        if not _valid_asset(asset):
            return false
    return true

func _fetch(url: String, limit: int) -> Dictionary:
    var request := HTTPRequest.new()
    request.timeout = 25
    request.body_size_limit = limit
    add_child(request)
    var error := request.request(url)
    if error != OK:
        request.queue_free()
        return {"ok": false}
    var result: Array = await request.request_completed
    request.queue_free()
    if result[0] != HTTPRequest.RESULT_SUCCESS or result[1] != 200:
        return {"ok": false}
    return {"ok": true, "body": result[3]}

func check_and_download() -> void:
    if busy:
        return
    busy = true
    var response := await _fetch(MANIFEST, MAX_MANIFEST)
    if not response.ok:
        busy = false
        patch_failed.emit("Не удалось получить манифест")
        return
    var data = JSON.parse_string(response.body.get_string_from_utf8())
    if not _valid_manifest(data):
        busy = false
        patch_failed.emit("Некорректный манифест")
        return
    var revision := int(data["revision"])
    var directory := "user://livepatch/"
    DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(directory))
    var all_ok := true
    for asset in data["assets"]:
        var filename := str(asset["sha256"]) + "." + str(asset["extension"])
        var path := directory + filename
        if FileAccess.file_exists(path) and FileAccess.get_sha256(path) == str(asset["sha256"]):
            continue
        var payload := await _fetch(ORIGIN + str(asset["url"]), MAX_IMAGE)
        if not payload.ok:
            all_ok = false
            break
        var bytes: PackedByteArray = payload.body
        if bytes.size() != int(asset["size"]):
            all_ok = false
            break
        var hash_context := HashingContext.new()
        hash_context.start(HashingContext.HASH_SHA256)
        hash_context.update(bytes)
        var digest: String = hash_context.finish().hex_encode()
        if digest != str(asset["sha256"]):
            all_ok = false
            break
        var temp := path + ".part"
        var file := FileAccess.open(temp, FileAccess.WRITE)
        if file == null:
            all_ok = false
            break
        file.store_buffer(bytes)
        file.close()
        if DirAccess.rename_absolute(ProjectSettings.globalize_path(temp), ProjectSettings.globalize_path(path)) != OK:
            all_ok = false
            break
    if all_ok:
        var output := FileAccess.open(directory + "manifest.json.tmp", FileAccess.WRITE)
        if output != null:
            output.store_string(JSON.stringify(data))
            output.close()
            all_ok = DirAccess.rename_absolute(ProjectSettings.globalize_path(directory + "manifest.json.tmp"), ProjectSettings.globalize_path(directory + "manifest.json")) == OK
        else:
            all_ok = false
    busy = false
    if all_ok:
        patch_ready.emit(revision)
    else:
        patch_failed.emit("Ошибка проверки или записи ресурсов")

func image_for(asset_id: String) -> Texture2D:
    var manifest_path := "user://livepatch/manifest.json"
    if not FileAccess.file_exists(manifest_path):
        return null
    var file := FileAccess.open(manifest_path, FileAccess.READ)
    if file == null:
        return null
    var data = JSON.parse_string(file.get_as_text())
    if not _valid_manifest(data):
        return null
    for asset in data["assets"]:
        if str(asset["id"]) != asset_id:
            continue
        var path := "user://livepatch/" + str(asset["sha256"]) + "." + str(asset["extension"])
        if not FileAccess.file_exists(path) or FileAccess.get_sha256(path) != str(asset["sha256"]):
            return null
        var image := Image.new()
        var err := image.load(path)
        if err != OK:
            return null
        return ImageTexture.create_from_image(image)
    return null
