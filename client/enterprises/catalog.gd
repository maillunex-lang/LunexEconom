extends Node
## Server-owned catalogue with conditional GET and a validated device cache.
const CACHE_PATH := "user://enterprise_catalog.json"
const ETAG_PATH := "user://enterprise_catalog_etag.txt"
var api: Node
var data: Dictionary = {}
var etag := ""

func configure(adapter: Node) -> void:
    api = adapter
    restore()

func restore() -> bool:
    if not FileAccess.file_exists(CACHE_PATH):
        return false
    var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(CACHE_PATH))
    if not _valid(parsed):
        return false
    data = parsed
    etag = FileAccess.get_file_as_string(ETAG_PATH).strip_edges() if FileAccess.file_exists(ETAG_PATH) else ""
    return true

func update() -> bool:
    if api == null:
        return false
    var response: Dictionary = await api.fetch("/catalog", HTTPClient.METHOD_GET, {}, etag)
    var code := int(response.get("code", 0))
    if code == 304:
        return _valid(data)
    if code != 200 or not _valid(response.get("data", null)):
        return false
    var snapshot: Dictionary = response["data"]
    var file := FileAccess.open(CACHE_PATH, FileAccess.WRITE)
    if file == null:
        return false
    file.store_string(JSON.stringify(snapshot))
    file.close()
    data = snapshot
    etag = str(response.get("etag", ""))
    var tag_file := FileAccess.open(ETAG_PATH, FileAccess.WRITE)
    if tag_file != null:
        tag_file.store_string(etag)
        tag_file.close()
    return true

func _valid(value: Variant) -> bool:
    return value is Dictionary and value.get("buildings") is Array and value.get("products") is Array and value.get("recipes") is Array and value.get("version") is String

func buildings() -> Array:
    return data.get("buildings", [])

func building(building_id: String) -> Dictionary:
    for item in buildings():
        if item is Dictionary and str(item.get("id", "")) == building_id:
            return item
    return {}

func eligible(item: Dictionary, zone: String, free_width: int, free_height: int) -> bool:
    var size: Dictionary = item.get("size", {})
    return zone in item.get("zones", []) and int(size.get("width", 0)) <= free_width and int(size.get("height", 0)) <= free_height and free_width > 0 and free_height > 0
