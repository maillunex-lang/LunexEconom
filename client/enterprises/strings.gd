extends RefCounted
const PATH := "res://data/enterprise_strings.json"
static var words: Dictionary = {}
static func get_text(key: String, args: Dictionary = {}) -> String:
    if words.is_empty():
        var value: Variant = JSON.parse_string(FileAccess.get_file_as_string(PATH))
        if value is Dictionary:
            words = value
    var result := str(words.get(key, words.get("error.generic", "Ошибка")))
    for name in args:
        result = result.replace("{" + str(name) + "}", str(args[name]))
    return result

static func error(response: Dictionary) -> String:
    if int(response.get("code", 0)) == 0:
        return get_text("error.network")
    var data: Dictionary = response.get("data", {})
    var key := "error." + str(data.get("error", "generic"))
    return get_text(key) if words.has(key) else get_text("error.generic")
