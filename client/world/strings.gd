extends RefCounted
const CoreStrings = preload("res://i18n/strings.gd")
const FILE := "res://data/world_strings.json"
const EXTRA := "res://data/polish_strings.json"
static var values: Dictionary = {}
static var extras: Dictionary = {}
static var loaded := false

static func get_text(key: String, args: Dictionary = {}) -> String:
    if not loaded:
        loaded = true
        var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(FILE))
        if parsed is Dictionary:
            values = parsed
        var more: Variant = JSON.parse_string(FileAccess.get_file_as_string(EXTRA))
        if more is Dictionary:
            extras = more
    if not extras.has(key) and not values.has(key):
        return CoreStrings.get_text(key,args)
    var output: String = str(extras.get(key,values.get(key,"")))
    for name in args:
        output = output.replace("{" + str(name) + "}",str(args[name]))
    return output
