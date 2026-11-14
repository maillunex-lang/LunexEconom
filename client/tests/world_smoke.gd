extends SceneTree
func _initialize() -> void:
    var script = load("res://world.gd")
    assert(script != null)
    var world = script.new()
    assert(world.cell_kind(10, 20) == world.cell_kind(10, 20))
    assert(world.cell_kind(0, 4) == 3)
    assert(world.cell_kind(19, 7) == 3)
    var pos: Vector2 = world.iso(6.0, 4.0)
    assert(world.cell_at(pos) == Vector2i(6, 4))
    var different := false
    for x in range(1, 30):
        if world.cell_kind(x, 2) != world.cell_kind(1, 2):
            different = true
    assert(different)
    var before: int = world.cell_kind(500, -700)
    world.expand_city(50)
    assert(world.expansion_radius > 500)
    assert(world.cell_kind(500, -700) == before)
    var roads = load("res://road_network.gd").new()
    var site := Vector2i(7, 9)
    assert(not roads.is_road(site))
    assert(roads.route(site, Vector2i(0, 0)).is_empty())
    var access: Array[Vector2i] = roads.connect_site(site)
    assert(access.size() > 1)
    assert(roads.add_path(access))
    var trip: Array[Vector2i] = roads.route(site, Vector2i(0, 0))
    assert(not trip.is_empty())
    assert(trip[0] == site and trip[trip.size() - 1] == Vector2i(0, 0))
    var invalid: Array[Vector2i] = [Vector2i(2, 2), Vector2i(20, 20)]
    assert(not roads.add_path(invalid))
    assert(not roads.is_road(Vector2i(2, 2)))
    print("WORLD_TEST_PASS seed/roads/projection/expansion/connected-route/disconnected-route")
    world.free()
    quit()
