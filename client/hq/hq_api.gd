extends RefCounted
## Strictly read-only HUD data transport. All money and company data come from the authoritative server.
const ROOT := "https://rikagro.ru/lunexeconom/api/"
const SAMPLE := "res://tests/hq_sample.json"
const CONFIG := "user://hq.cfg"

static func sample_enabled() -> bool:
    var config := ConfigFile.new()
    if config.load(CONFIG) != OK:
        return false  # Production always uses authenticated server data until the player opts into demo mode
    return bool(config.get_value("data", "sample", false))

static func set_sample_enabled(value: bool) -> void:
    var config := ConfigFile.new()
    config.load(CONFIG)
    config.set_value("data", "sample", value)
    config.save(CONFIG)

static func sample() -> Dictionary:
    var file := FileAccess.open(SAMPLE, FileAccess.READ)
    if file == null:
        return {}
    var parsed = JSON.parse_string(file.get_as_text())
    return parsed if parsed is Dictionary else {}

static func authorize() -> PackedStringArray:
    if not GameSession.is_authenticated():
        return PackedStringArray()
    return PackedStringArray(["Authorization: Bearer " + GameSession.access_token])
