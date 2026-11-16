extends Node
const PublicBase = preload("res://config/public_base.gd")
## Isolated HTTP adapter; tests replace transport with a callable mock.
var base_url := PublicBase.api_url()
var token := ""
var mock: Callable
var refresh: Callable

func fetch(path: String, method: int = HTTPClient.METHOD_GET, payload: Dictionary = {}, etag: String = "") -> Dictionary:
    var answer: Dictionary = await _once(path, method, payload, etag)
    if int(answer.get("code", 0)) == 401 and refresh.is_valid():
        var renewed: Variant = await refresh.call()
        if renewed is String and not renewed.is_empty():
            token = renewed
            answer = await _once(path, method, payload, etag)
    return answer

func _once(path: String, method: int, payload: Dictionary, etag: String) -> Dictionary:
    var headers := PackedStringArray(["Accept: application/json", "Content-Type: application/json"])
    if not token.is_empty():
        headers.append("Authorization: Bearer " + token)
    if not etag.is_empty():
        headers.append("If-None-Match: " + etag)
    if mock.is_valid():
        var simulated: Variant = await mock.call(path, method, payload, headers)
        return simulated if simulated is Dictionary else {"code": 0, "data": {}}
    base_url = PublicBase.api_url()
    if base_url.is_empty():
        return {"code": 0, "data": {"error": "service_unavailable"}}
    var request := HTTPRequest.new()
    request.timeout = 12.0
    add_child(request)
    var body := JSON.stringify(payload) if method in [HTTPClient.METHOD_POST, HTTPClient.METHOD_PUT, HTTPClient.METHOD_PATCH] else ""
    var error := request.request(base_url + path, headers, method, body)
    if error != OK:
        request.queue_free()
        return {"code": 0, "data": {}, "error": error}
    var finished: Array = await request.request_completed
    request.queue_free()
    if int(finished[0]) != HTTPRequest.RESULT_SUCCESS:
        return {"code": 0, "data": {}, "error": int(finished[0])}
    var response_etag := ""
    for header in finished[2]:
        var raw: String = str(header)
        if raw.to_lower().begins_with("etag:"):
            response_etag = raw.substr(5).strip_edges()
            break
    var parsed: Variant = JSON.parse_string((finished[3] as PackedByteArray).get_string_from_utf8())
    return {"code": int(finished[1]), "data": parsed if parsed is Dictionary else {}, "etag": response_etag}
