extends RefCounted
## Integer-only Russian money, unit labels and game-day declension.
const FILE := "res://data/polish_strings.json"
static var _words: Dictionary = {}

static func _label(key: String) -> String:
    if _words.is_empty():
        var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(FILE))
        if parsed is Dictionary:
            _words = parsed
    return str(_words.get(key,key))

static func number(value: Variant) -> String:
    var n := int(value)
    var raw := str(n)
    var sign := ""
    if raw.begins_with("-"):
        sign = "-"
        raw = raw.substr(1)
    var result := ""
    while raw.length() > 3:
        result = " " + raw.substr(raw.length()-3) + result
        raw = raw.substr(0,raw.length()-3)
    return sign + raw + result

static func money(value: Variant) -> String:
    return number(value) + " ₽"

static func days(value: Variant) -> String:
    var n := maxi(0,int(value))
    var ending := _label("format.game_day.many")
    if n % 100 < 11 or n % 100 > 14:
        if n % 10 == 1:
            ending = _label("format.game_day.one")
        elif n % 10 in [2,3,4]:
            ending = _label("format.game_day.few")
    return number(n) + " " + ending
