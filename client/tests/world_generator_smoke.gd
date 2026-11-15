extends SceneTree
const Generator = preload("res://world/generator.gd")
func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string("res://tests/vectors_world_seed_v1.json"))
    assert(parsed is Dictionary, "Missing canonical vectors")
    var data: Dictionary = parsed
    for item in data["cells"]:
        var x := int(item["x"])
        var y := int(item["y"])
        var value := Generator.noise(int(data["seed"]), x, y)
        assert(Generator.unsigned_decimal(value) == str(item["noise"]), "noise x=%d y=%d" % [x, y])
        assert(Generator.terrain(int(data["seed"]), x, y) == item["terrain"], "terrain x=%d y=%d" % [x, y])
    for item in data["zones"]:
        assert(Generator.zone(int(item["x"]), int(item["y"]), 0, 0, 12, int(item["level"])) == item["zone"], "zone mismatch")
    for i in range(data["radii"].size()):
        assert(Generator.radius_at_level(12, i + 1) == int(data["radii"][i]), "radius mismatch")
    print("world generator smoke OK: %d cells, %d zones" % [data["cells"].size(), data["zones"].size()])
    quit(0)
