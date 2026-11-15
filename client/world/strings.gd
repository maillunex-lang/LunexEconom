extends RefCounted
const CoreStrings = preload("res://i18n/strings.gd")
const FILE := "res://data/world_strings.json"
static var values: Dictionary = {}
static var loaded := false

static func get_text(key: String, args: Dictionary = {}) -> String:
    if not loaded:
        loaded = true
        var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(FILE))
        if parsed is Dictionary:
            values = parsed
    if not values.has(key):
        return CoreStrings.get_text(key, args)
    var output: String = str(values[key])
    for name in args:
        output = output.replace("{" + str(name) + "}", str(args[name]))
    return output
