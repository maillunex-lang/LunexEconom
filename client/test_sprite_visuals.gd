extends RefCounted
## Optional test art. The game keeps procedural graphics when sprites are absent.
const ROOT := "res://assets/test_buildings/"
const SPRITES := {
    "grocery": "grocery_1x1.png",
    "road": "road_asphalt_1x1.png",
    "house_a": "house_panel_a_1x1.png",
    "house_b": "house_panel_b_1x1.png",
    "house_2x1": "house_stalinka_2x1.png"
}
var textures: Dictionary = {}

func _init() -> void:
    for key in SPRITES:
        var path: String = ROOT + SPRITES[key]
        if ResourceLoader.exists(path):
            var resource = load(path)
            if resource is Texture2D:
                textures[key] = resource

func texture_for(key: String) -> Texture2D:
    return textures.get(key, null)

func house_variant(object_id: String, cell: Vector2i, is_long: bool) -> String:
    if is_long: return "house_2x1"
    var value: int = cell.x * 31 + cell.y * 17
    for byte in object_id.to_utf8_buffer():
        value = (value * 33 + int(byte)) & 0x7fffffff
    return "house_a" if posmod(value, 2) == 0 else "house_b"
