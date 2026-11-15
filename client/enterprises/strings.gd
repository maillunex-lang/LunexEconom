extends RefCounted
const PATH := "res://data/enterprise_strings.json"
const EXTRA := "res://data/polish_strings.json"
static var words: Dictionary = {}
static var extras: Dictionary = {}

static func _ensure() -> void:
    if words.is_empty():
        var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(PATH))
        if parsed is Dictionary:
            words = parsed
    if extras.is_empty():
        var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(EXTRA))
        if parsed is Dictionary:
            extras = parsed

static func has_text(key: String) -> bool:
    _ensure()
    return extras.has(key) or words.has(key)

static func get_text(key: String, args: Dictionary = {}) -> String:
    _ensure()
    var result := str(extras.get(key,words.get(key,words.get("error.generic","Ошибка"))))
    for name in args:
        result = result.replace("{" + str(name) + "}",str(args[name]))
    return result

static func error(response: Dictionary) -> String:
    _ensure()
    if int(response.get("code",0)) == 0:
        return get_text("error.build.network")
    var data: Dictionary = response.get("data", {})
    var raw := str(data.get("error","unknown"))
    var key := "error.build." + raw
    if extras.has(key):
        return get_text(key)
    return get_text("error.build.unknown") + "\n" + get_text("error.build.code",{"code":raw})
