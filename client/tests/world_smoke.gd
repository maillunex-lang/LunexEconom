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
    print("WORLD_TEST_PASS seed/roads/projection")
    world.free()
    quit()
