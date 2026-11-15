extends Node
## Sequential manifest + detached RSA signature retrieval, no redirects.
signal loaded(kind: String, data: Dictionary)
signal failed(kind: String, reason: String)

const PublicBase = preload("res://config/public_base.gd")
const Verifier = preload("res://update/manifest_verifier.gd")
var busy := false

func fetch(kind: String) -> void:
    if busy or not kind in ["update", "content"]:
        return
    busy = true
    var raw := await _get_bytes(PublicBase.url(kind + ".json"), 65536)
    if raw.is_empty():
        busy = false
        failed.emit(kind, "Нет подписанного манифеста")
        return
    var signature := await _get_bytes(PublicBase.url(kind + ".json.sig"), 4096)
    busy = false
    if not Verifier.verify(raw, signature.get_string_from_utf8()):
        failed.emit(kind, "Подпись манифеста не прошла проверку")
        return
    var data = JSON.parse_string(raw.get_string_from_utf8())
    if (kind == "update" and not Verifier.valid_update(data)) or (kind == "content" and not Verifier.valid_content(data)):
        failed.emit(kind, "Неверные поля манифеста")
        return
    loaded.emit(kind, data)

func _get_bytes(url: String, maximum: int) -> PackedByteArray:
    if not PublicBase.allows_file_url(url):
        return PackedByteArray()
    var request := HTTPRequest.new()
    request.timeout = 20
    request.max_redirects = 0
    request.body_size_limit = maximum
    add_child(request)
    var error := request.request(url)
    if error != OK:
        request.queue_free()
        return PackedByteArray()
    var response: Array = await request.request_completed
    request.queue_free()
    if int(response[0]) != HTTPRequest.RESULT_SUCCESS or int(response[1]) != 200:
        return PackedByteArray()
    var raw: PackedByteArray = response[3]
    if raw.size() <= 0 or raw.size() > maximum:
        return PackedByteArray()
    return raw
