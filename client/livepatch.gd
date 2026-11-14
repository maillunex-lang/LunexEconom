extends Node
## Opt-in, data-only patch downloader (PNG/WebP images only). Not autoloaded and never started automatically.
## Trust model: the manifest is accepted only with a valid RSA-SHA256 signature made OFFLINE with the administrator's private key and
## verified here against the public key shipped in the APK (res://livepatch_public.pem). Without that key nothing is ever activated.
## Every image is size-limited, hash-checked and its header dimensions are read BEFORE any decoder sees it (decompression-bomb guard).
signal patch_ready(revision: int)
signal patch_failed(reason: String)

const ORIGIN := "https://rikagro.ru/lunexeconom/admin/patch/"
const MANIFEST := ORIGIN + "manifest.json"
const SIGNATURE := ORIGIN + "manifest.sig"
const PUBLIC_KEY_PATH := "res://livepatch_public.pem"
const DIRECTORY := "user://livepatch/"
const MAX_MANIFEST := 512 * 1024
const MAX_SIGNATURE := 4096
const MAX_IMAGE := 8 * 1024 * 1024
const MAX_ASSETS := 300
const MAX_DIMENSION := 2048
const MAX_PIXELS := 4 * 1024 * 1024
const HEX := "0123456789abcdef"
var busy := false
var public_key_path := PUBLIC_KEY_PATH      # overridable for tests only

# ---------- header-only image checks ----------
static func _be32(b: PackedByteArray, at: int) -> int:
    return (b[at] << 24) | (b[at + 1] << 16) | (b[at + 2] << 8) | b[at + 3]

static func _le(b: PackedByteArray, at: int, count: int) -> int:
    var value := 0
    for i in range(count):
        value |= b[at + i] << (8 * i)
    return value

## Width and height read from the file header only; Vector2i.ZERO when the header is not a plain PNG / WebP header.
static func header_dimensions(extension: String, head: PackedByteArray) -> Vector2i:
    if extension == "png":
        if head.size() < 24:
            return Vector2i.ZERO
        var signature := PackedByteArray([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
        if head.slice(0, 8) != signature or head.slice(12, 16).get_string_from_ascii() != "IHDR":
            return Vector2i.ZERO
        return Vector2i(_be32(head, 16), _be32(head, 20))
    if extension == "webp":
        if head.size() < 30 or head.slice(0, 4).get_string_from_ascii() != "RIFF" or head.slice(8, 12).get_string_from_ascii() != "WEBP":
            return Vector2i.ZERO
        var kind := head.slice(12, 16).get_string_from_ascii()
        if kind == "VP8 ":
            if head[23] != 0x9D or head[24] != 0x01 or head[25] != 0x2A:
                return Vector2i.ZERO
            return Vector2i(_le(head, 26, 2) & 0x3FFF, _le(head, 28, 2) & 0x3FFF)
        if kind == "VP8L":
            if head[20] != 0x2F:
                return Vector2i.ZERO
            var bits := _le(head, 21, 4)
            return Vector2i((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
        if kind == "VP8X":
            return Vector2i(_le(head, 24, 3) + 1, _le(head, 27, 3) + 1)
    return Vector2i.ZERO

static func dimensions_ok(size: Vector2i) -> bool:
    return size.x >= 1 and size.y >= 1 and size.x <= MAX_DIMENSION and size.y <= MAX_DIMENSION and size.x * size.y <= MAX_PIXELS

static func bytes_dimensions_ok(extension: String, bytes: PackedByteArray) -> bool:
    return dimensions_ok(header_dimensions(extension, bytes.slice(0, 64)))

static func file_dimensions_ok(path: String, extension: String) -> bool:
    var file := FileAccess.open(path, FileAccess.READ)
    if file == null:
        return false
    var head := file.get_buffer(64)
    file.close()
    return dimensions_ok(header_dimensions(extension, head))

# ---------- signature ----------
func load_public_key() -> CryptoKey:
    if not FileAccess.file_exists(public_key_path):
        return null
    var key := CryptoKey.new()
    if key.load(public_key_path, true) != OK:
        return null
    return key

## True only when `signature_b64` is a valid RSA-SHA256 (PKCS#1 v1.5) signature of EXACTLY these manifest bytes under `key`.
func verify_manifest(manifest_bytes: PackedByteArray, signature_b64: String, key: CryptoKey) -> bool:
    if key == null or manifest_bytes.is_empty() or signature_b64.is_empty() or signature_b64.length() > MAX_SIGNATURE:
        return false
    var signature := Marshalls.base64_to_raw(signature_b64.strip_edges())
    if signature.is_empty():
        return false
    var context := HashingContext.new()
    context.start(HashingContext.HASH_SHA256)
    context.update(manifest_bytes)
    var digest := context.finish()
    return Crypto.new().verify(HashingContext.HASH_SHA256, digest, signature, key)

## The cached manifest, re-verified against its stored signature, or null.
func load_verified_manifest(name: String = "manifest") -> Variant:
    var key := load_public_key()
    if key == null:
        return null
    var json_path := DIRECTORY + name + ".json"
    var sig_path := DIRECTORY + name + ".sig"
    if not FileAccess.file_exists(json_path) or not FileAccess.file_exists(sig_path):
        return null
    var raw := FileAccess.get_file_as_bytes(json_path)
    var sig := FileAccess.get_file_as_string(sig_path)
    if not verify_manifest(raw, sig, key):
        return null
    var data: Variant = JSON.parse_string(raw.get_string_from_utf8())
    return data if _valid_manifest(data) else null

func current_revision() -> int:
    var path := DIRECTORY + "manifest.json"
    if not FileAccess.file_exists(path):
        return 0
    var data: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
    if not _valid_manifest(data):
        return 0
    return int(data["revision"])

# ---------- validation ----------
## JSON numbers arrive as float in Godot (3 is 3.0): accept whole numbers of either type.
static func _is_whole(value: Variant) -> bool:
    return typeof(value) == TYPE_INT or (typeof(value) == TYPE_FLOAT and value == floorf(value))

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
    if digest.length() != 64:
        return false
    for character in digest:
        if not (character in HEX):          # lower-case hexadecimal only: no signs, no "0x", nothing path-like
            return false
    var size: Variant = item.get("size", 0)
    if not _is_whole(size) or size <= 0 or size > MAX_IMAGE:
        return false
    return str(item.get("url", "")) == "blobs/" + digest + "." + extension

func _valid_manifest(data: Variant) -> bool:
    if not data is Dictionary or data.get("schema") != 1:
        return false
    if not _is_whole(data.get("revision")) or int(data["revision"]) < 0:
        return false
    if not data.get("assets") is Array or data["assets"].size() > MAX_ASSETS:
        return false
    for asset in data["assets"]:
        if not _valid_asset(asset):
            return false
    return true

# ---------- files ----------
func _write_atomic(path: String, bytes: PackedByteArray) -> bool:
    var temporary := path + ".tmp"
    var output := FileAccess.open(temporary, FileAccess.WRITE)
    if output == null:
        return false
    output.store_buffer(bytes)
    output.close()
    return DirAccess.rename_absolute(ProjectSettings.globalize_path(temporary), ProjectSettings.globalize_path(path)) == OK

func _copy_atomic(from_path: String, to_path: String) -> bool:
    return FileAccess.file_exists(from_path) and _write_atomic(to_path, FileAccess.get_file_as_bytes(from_path))

## Remove downloaded images that neither the current nor the previous manifest uses (and leftover temporary files).
func collect_garbage(directory: String = DIRECTORY) -> int:
    var keep := {"manifest.json": true, "manifest.sig": true, "manifest.previous.json": true, "manifest.previous.sig": true}
    for name: String in ["manifest", "manifest.previous"]:
        var path: String = directory + name + ".json"
        if FileAccess.file_exists(path):
            var data: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
            if _valid_manifest(data):
                for asset in data["assets"]:
                    keep[str(asset["sha256"]) + "." + str(asset["extension"])] = true
    var removed := 0
    var dir := DirAccess.open(directory)
    if dir == null:
        return 0
    for file_name in dir.get_files():
        if not keep.has(file_name):
            if dir.remove(file_name) == OK:
                removed += 1
    return removed

func restore_previous() -> bool:
    if busy:
        return false
    var previous: Variant = load_verified_manifest("manifest.previous")
    if previous == null:
        return false
    for asset in previous["assets"]:
        var path := DIRECTORY + str(asset["sha256"]) + "." + str(asset["extension"])
        if not FileAccess.file_exists(path) or FileAccess.get_sha256(path) != str(asset["sha256"]):
            return false
    if not (_copy_atomic(DIRECTORY + "manifest.previous.json", DIRECTORY + "manifest.json") and _copy_atomic(DIRECTORY + "manifest.previous.sig", DIRECTORY + "manifest.sig")):
        return false
    patch_ready.emit(int(previous["revision"]))
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

func _fail(reason: String) -> void:
    busy = false
    patch_failed.emit(reason)

func check_and_download() -> void:
    if busy:
        return
    busy = true
    var key := load_public_key()
    if key == null:
        _fail("В приложении нет ключа проверки обновлений")
        return
    var response := await _fetch(MANIFEST, MAX_MANIFEST)
    var signature_response := await _fetch(SIGNATURE, MAX_SIGNATURE)
    if not response.ok or not signature_response.ok:
        _fail("Не удалось получить манифест")
        return
    var manifest_bytes: PackedByteArray = response.body
    var signature_text: String = (signature_response.body as PackedByteArray).get_string_from_ascii()
    if not verify_manifest(manifest_bytes, signature_text, key):
        _fail("Подпись манифеста неверна")
        return
    var data: Variant = JSON.parse_string(manifest_bytes.get_string_from_utf8())
    if not _valid_manifest(data):
        _fail("Некорректный манифест")
        return
    var revision := int(data["revision"])
    if revision <= current_revision():
        busy = false
        return
    DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(DIRECTORY))
    for asset in data["assets"]:
        var filename := str(asset["sha256"]) + "." + str(asset["extension"])
        var path := DIRECTORY + filename
        if FileAccess.file_exists(path) and FileAccess.get_sha256(path) == str(asset["sha256"]):
            continue
        var payload := await _fetch(ORIGIN + str(asset["url"]), MAX_IMAGE)
        if not payload.ok:
            _fail("Ошибка загрузки ресурса")
            return
        var bytes: PackedByteArray = payload.body
        if bytes.size() != int(asset["size"]):
            _fail("Размер ресурса не совпал")
            return
        var hash_context := HashingContext.new()
        hash_context.start(HashingContext.HASH_SHA256)
        hash_context.update(bytes)
        if hash_context.finish().hex_encode() != str(asset["sha256"]):
            _fail("Контрольная сумма ресурса не совпала")
            return
        if not bytes_dimensions_ok(str(asset["extension"]), bytes):
            _fail("Недопустимый размер изображения")
            return
        if not _write_atomic(path, bytes):
            _fail("Ошибка записи ресурса")
            return
    # keep the previously verified release for a manual rollback, then switch to the new one (manifest last)
    if FileAccess.file_exists(DIRECTORY + "manifest.json") and FileAccess.file_exists(DIRECTORY + "manifest.sig"):
        if not (_copy_atomic(DIRECTORY + "manifest.json", DIRECTORY + "manifest.previous.json") and _copy_atomic(DIRECTORY + "manifest.sig", DIRECTORY + "manifest.previous.sig")):
            _fail("Ошибка сохранения предыдущей версии")
            return
    if not (_write_atomic(DIRECTORY + "manifest.sig", signature_text.to_ascii_buffer()) and _write_atomic(DIRECTORY + "manifest.json", manifest_bytes)):
        _fail("Ошибка записи манифеста")
        return
    collect_garbage()
    busy = false
    patch_ready.emit(revision)

func image_for(asset_id: String) -> Texture2D:
    var data: Variant = load_verified_manifest()
    if data == null:
        return null
    for asset in data["assets"]:
        if str(asset["id"]) != asset_id:
            continue
        var path := DIRECTORY + str(asset["sha256"]) + "." + str(asset["extension"])
        if not FileAccess.file_exists(path) or FileAccess.get_sha256(path) != str(asset["sha256"]):
            return null
        if not file_dimensions_ok(path, str(asset["extension"])):      # header first: never decode an oversized canvas
            return null
        var image := Image.new()
        if image.load(path) != OK:
            return null
        return ImageTexture.create_from_image(image)
    return null
