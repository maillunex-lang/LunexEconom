extends SceneTree
## Procedural background never overrides server roads/buildings/water.
func _initialize() -> void:
    var layout = load("res://city_layout.gd")
    if layout == null:
        push_error("CITY_LAYOUT_SMOKE_FAIL missing script")
        quit(1)
        return
    var city := {"id":"ufa", "x":0, "y":0, "radius":48, "specialization":"нефтехимия"}
    var first: Dictionary = {}
    for x in range(-40,40):
        for y in range(-40,40):
            first[Vector2i(x,y)] = layout.visual_at(city,x,y,0)
            for terrain_kind in [3,4,5,6]:
                assert(layout.visual_at(city,x,y,terrain_kind) == "", "authoritative terrain must win")
    for x in range(-40,40):
        for y in range(-40,40):
            assert(first[Vector2i(x,y)] == layout.visual_at(city,x,y,0), "deterministic two passes")
    assert(layout.visual_at(city,100,100,0) == "")
    assert(layout.cities_in_chunk([city], Vector2i(0,0)).size() == 1)
    assert(layout.cities_in_chunk([city], Vector2i(100,100)).is_empty())
    var classes: Dictionary = {}
    for kind in first.values():
        if kind != "":
            classes[kind] = true
    assert(classes.has("street") and classes.has("house") and classes.has("square"))
    print("CITY_LAYOUT_SMOKE_PASS repeatable/roads/water/buildings/lod")
    quit(0)
