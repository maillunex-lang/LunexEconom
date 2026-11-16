extends RefCounted
## Approved GDD-26 tokens, loaded once for all Forest Glass components.
const PATH := "res://theme/tokens_proposed.json"
static var _cache: Dictionary = {}

static func data() -> Dictionary:
    if _cache.is_empty():
        var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(PATH))
        assert(parsed is Dictionary, "UI token catalogue is invalid")
        _cache = parsed
    return _cache
