extends RefCounted
## Bounded, atomic, checksum-validated offline cache. Only public world data is stored.
const FORMAT := 2
const ROOT := "user://map_cache"
const LIMIT_BYTES := 50 * 1024 * 1024
var scope := ""

func set_server(base_url: String) -> void:
    var next_scope := base_url.sha256_text()
    var settings := _read(ROOT + "/_scope.json")
    if str(settings.get("scope", "")) != next_scope or int(settings.get("format", -1)) != FORMAT:
        _clear_directory(ROOT)
    scope = next_scope
    DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(ROOT))
    _write(ROOT + "/_scope.json", {"scope":scope, "format":FORMAT})

func _clear_directory(path: String) -> void:
    var folder := DirAccess.open(path)
    if folder == null:
        return
    for name in folder.get_files():
        DirAccess.remove_absolute(ProjectSettings.globalize_path(path.path_join(name)))
    for name in folder.get_directories():
        _clear_directory(path.path_join(name))
    DirAccess.remove_absolute(ProjectSettings.globalize_path(path))

func _fingerprint(payload: Dictionary) -> String:
    # Hash canonical key-order JSON; JSON.parse_string converts object ordering
    # into a different Dictionary order on a fresh process.
    return _canonical(payload).sha256_text()

func _canonical(value: Variant) -> String:
    if value is Dictionary:
        var parts: Array[String] = []
        var names: Array = value.keys()
        names.sort_custom(func(a: Variant,b: Variant) -> bool: return str(a) < str(b))
        for name in names:
            parts.append(JSON.stringify(str(name)) + ":" + _canonical(value[name]))
        return "{" + ",".join(parts) + "}"
    if value is Array:
        var parts: Array[String] = []
        for item in value:
            parts.append(_canonical(item))
        return "[" + ",".join(parts) + "]"
    if value is float:
        # JSON parser represents integer JSON numbers as floats; stringify
        # numbers identically before and after a disk roundtrip.
        var f: float = value
        if f == floorf(f) and absf(f) <= 9007199254740991.0:
            return str(int(f))
    return JSON.stringify(value)

func _read(path: String) -> Dictionary:
    if not FileAccess.file_exists(path):
        return {}
    var parser := JSON.new()
    if parser.parse(FileAccess.get_file_as_string(path)) != OK:
        DirAccess.remove_absolute(ProjectSettings.globalize_path(path))
        return {}
    var parsed: Variant = parser.data
    if not (parsed is Dictionary and parsed.has("data") and parsed.has("sha256")):
        DirAccess.remove_absolute(ProjectSettings.globalize_path(path))
        return {}
    var payload: Variant = parsed["data"]
    if not (payload is Dictionary and _fingerprint(payload) == str(parsed["sha256"])):
        DirAccess.remove_absolute(ProjectSettings.globalize_path(path))
        return {}
    return payload

func _write(path: String, payload: Dictionary) -> void:
    DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(path.get_base_dir()))
    var tmp := path + ".tmp"
    var file := FileAccess.open(tmp, FileAccess.WRITE)
    if file == null:
        return
    file.store_string(JSON.stringify({"data":payload, "sha256":_fingerprint(payload)}))
    file.flush()
    file.close()
    if DirAccess.rename_absolute(ProjectSettings.globalize_path(tmp), ProjectSettings.globalize_path(path)) != OK:
        DirAccess.remove_absolute(ProjectSettings.globalize_path(tmp))

func _city_path(city: String) -> String:
    return ROOT + "/" + city.replace("/", "_").replace(".", "_").replace("\\", "_")

func _chunk_path(city: String, key: Vector2i) -> String:
    return _city_path(city).path_join("%d_%d.json" % [key.x,key.y])

func get_cities() -> Array:
    var result := _read(ROOT + "/_cities.json")
    if str(result.get("scope", "")) != scope or int(result.get("format", -1)) != FORMAT:
        return []
    var value: Variant = result.get("cities")
    return value if value is Array else []

func save_cities(cities: Array) -> void:
    _write(ROOT + "/_cities.json", {"scope":scope, "format":FORMAT, "cities":cities})

func get_cursor() -> int:
    var result := _read(ROOT + "/_cursor.json")
    return maxi(0, int(result.get("cursor", 0))) if str(result.get("scope", "")) == scope else 0

func save_cursor(value: int) -> void:
    _write(ROOT + "/_cursor.json", {"scope":scope, "cursor":value})

func get_chunk(city: String, key: Vector2i) -> Dictionary:
    var result := _read(_chunk_path(city,key))
    if int(result.get("format", -1)) != FORMAT or str(result.get("scope", "")) != scope:
        return {}
    if int(result.get("cx", 99999999)) != key.x or int(result.get("cy", 99999999)) != key.y:
        return {}
    var snapshot: Variant = result.get("snapshot", {})
    if not _valid_snapshot(snapshot, key):
        DirAccess.remove_absolute(ProjectSettings.globalize_path(_chunk_path(city,key)))
        return {}
    if not (result.get("parcels", []) is Array):
        return {}
    return {"etag":str(result.get("etag", "")), "snapshot":snapshot, "parcels":result.get("parcels", [])}

func _valid_snapshot(value: Variant, key: Vector2i) -> bool:
    if not (value is Dictionary and value.get("terrain") is Array and value.get("zones") is Array and value.get("roads") is Array):
        return false
    if int(value.get("cx", key.x)) != key.x or int(value.get("cy", key.y)) != key.y:
        return false
    for layer in ["terrain", "zones", "roads"]:
        var rows: Array = value[layer]
        if rows.size() != 12:
            return false
        for row in rows:
            if not (row is Array) or row.size() != 12:
                return false
    return true

func save_chunk(city: String, key: Vector2i, entry: Dictionary) -> void:
    if not entry.has("snapshot") or not _valid_snapshot(entry["snapshot"],key):
        return
    _write(_chunk_path(city,key), {"format":FORMAT, "scope":scope,
        "cx":key.x,"cy":key.y,"etag":str(entry.get("etag", "")),
        "snapshot":entry["snapshot"],"parcels":entry.get("parcels", [])})
    enforce_limit()

func invalidate_chunk(city: String, key: Vector2i) -> void:
    DirAccess.remove_absolute(ProjectSettings.globalize_path(_chunk_path(city,key)))

func _file_entries(folder: String, output: Array) -> void:
    var dir := DirAccess.open(folder)
    if dir == null:
        return
    for name in dir.get_files():
        var path: String = folder.path_join(name)
        if name.ends_with(".json") and not name.begins_with("_"):
            var access := FileAccess.open(path, FileAccess.READ)
            if access != null:
                output.append({"path":path, "size":access.get_length(),
                    "modified":FileAccess.get_modified_time(path)})
    for name in dir.get_directories():
        _file_entries(folder.path_join(name), output)

func enforce_limit() -> void:
    var files: Array = []
    _file_entries(ROOT, files)
    var size_bytes := 0
    for file in files:
        size_bytes += int(file["size"])
    if size_bytes <= LIMIT_BYTES:
        return
    files.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
        return int(a["modified"]) < int(b["modified"]))
    for file in files:
        if size_bytes <= LIMIT_BYTES:
            break
        if DirAccess.remove_absolute(ProjectSettings.globalize_path(str(file["path"]))) == OK:
            size_bytes -= int(file["size"])
