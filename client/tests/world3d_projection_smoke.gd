extends SceneTree
const GRID = preload("res://world3d/grid_projection.gd")
func _initialize() -> void:
    for cell in [Vector2i.ZERO, Vector2i(7, -9), Vector2i(-25, 38)]:
        assert(GRID.world_to_cell(GRID.cell_to_world(cell)) == cell)
    assert(GRID.chunk_for(Vector2i(-1, -13)) == Vector2i(-1, -2))
    call_deferred("_scene_test")
func _scene_test() -> void:
    var scene: PackedScene = load("res://world3d/world3d.tscn")
    var world := scene.instantiate()
    root.add_child(world)
    await process_frame
    assert(world.camera != null)
    assert(world.chunk_nodes.size() == 25)
    assert(world.selected_cell == Vector2i(-99999, -99999))
    print("WORLD3D_PROTOTYPE_PASS chunks=", world.chunk_nodes.size())
    quit(0)