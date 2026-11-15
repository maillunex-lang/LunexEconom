extends RefCounted
## Runtime lookup from the generated, reviewed Russian text catalogue.
const PATH := "res://data/strings.json"
static var _values: Dictionary = {}
static var _loaded := false

static func load_catalog() -> void:
    if _loaded:
        return
    _loaded = true
    if not FileAccess.file_exists(PATH):
        push_warning("Missing localisation catalogue: " + PATH)
        return
    var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(PATH))
    if parsed is Dictionary:
        _values = parsed
    else:
        push_warning("Invalid localisation catalogue: " + PATH)

static func get_text(key: String, substitutions: Dictionary = {}) -> String:
    load_catalog()
    if not _values.has(key):
        push_warning("Missing Russian UI string: " + key)
        return key
    var result: String = str(_values[key])
    for name in substitutions:
        result = result.replace("{" + str(name) + "}", str(substitutions[name]))
    return result

static func has_key(key: String) -> bool:
    load_catalog()
    return _values.has(key)
