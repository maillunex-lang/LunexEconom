extends SceneTree
const ADAPTER = preload("res://world3d/server_visual_adapter.gd")
func _initialize() -> void:
    var a = ADAPTER.new()
    a.apply_chunk(Vector2i.ZERO, [
        {"x": 1, "y": 1, "kind": "building_created", "building_kind": "factory", "object_id": "factory-1", "owner": "alice"},
        {"x": 2, "y": 1, "kind": "building_created", "building_kind": "factory", "object_id": "factory-1", "owner": "alice"},
        {"x": 3, "y": 1, "kind": "road_changed"}
    ])
    assert(a.objects.size() == 1)
    assert(a.objects["factory-1"]["footprint"].size() == 2)
    assert(a.object_center("factory-1") == Vector2(1.5, 1.0))
    assert(a.roads.has(Vector2i(3, 1)))
    a.apply_event({"kind": "building_removed", "object_id": "factory-1", "cells": [[1,1],[2,1]]})
    assert(a.objects.is_empty())
    a.apply_chunk(Vector2i.ZERO, [])
    assert(a.roads.is_empty())
    call_deferred("_test_scene")
func _test_scene() -> void:
    var scene: PackedScene = load("res://world3d/world3d.tscn")
    var world = scene.instantiate()
    root.add_child(world)
    await process_frame
    world.apply_chunk_snapshot(Vector2i.ZERO, [
        {"x": 1, "y": 1, "kind": "building_created", "building_kind": "mine", "object_id": "mine-1", "owner": "bob"},
        {"x": 1, "y": 2, "kind": "building_created", "building_kind": "mine", "object_id": "mine-1", "owner": "bob"},
        {"x": 2, "y": 1, "kind": "road_changed"}
    ])
    assert(world.building_nodes.size() == 1)
    assert(world.road_nodes.size() == 1)
    assert(world.building_nodes["mine-1"].scene_file_path.ends_with("mine.glb"))
    var old_node = world.building_nodes["mine-1"]
    world.apply_server_event({"kind": "building_created", "building_kind": "mine", "object_id": "mine-1", "owner": "bob", "cells": [[2,2]]})
    assert(world.building_nodes.size() == 1)
    assert(world.building_nodes["mine-1"] != old_node)
    assert(world.visuals.objects["mine-1"]["footprint"].size() == 3)
    world.apply_server_event({"kind": "building_removed", "object_id": "mine-1", "cells": [[1,1],[1,2],[2,2]]})
    assert(world.building_nodes.is_empty())
    print("WORLD3D_SERVER_SYNC_PASS")
    quit(0)