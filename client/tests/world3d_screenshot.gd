extends SceneTree
## Development helper (not a CI test): renders the 3D world with sample buildings and saves PNG screenshots.
## Run with a display: xvfb-run godot --path client -s tests/world3d_screenshot.gd -- <output_dir>
func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	var args := OS.get_cmdline_user_args()
	var out_dir: String = args[0] if args.size() > 0 else "user://"
	var host: Control = load("res://world.tscn").instantiate()
	get_root().add_child(host)
	await process_frame
	var world = host.world
	var houses := [[[3, 2]], [[2, -2]], [[-2, 2], [-2, 3]], [[-3, -2], [-3, -3], [-3, -4]], [[5, 2]], [[2, 3]], [[-2, -5], [-2, -6]], [[6, -2]], [[2, 5], [2, 6], [2, 7]], [[-5, 2]], [[-6, -2]], [[3, -6]], [[5, -3], [5, -4]], [[-6, 3]], [[1, -6]], [[-1, 5]]]
	var i := 0
	for cells in houses:
		world.apply_server_event({"kind": "building_created", "building_kind": "house", "owner": "town:ufa", "object_id": "h%d" % i, "cells": cells})
		i += 1
	world.apply_server_event({"kind": "road_changed", "cells": [[1, 2], [1, 3], [1, 4], [1, 5], [1, 6], [1, 7], [-1, -2], [-1, -3], [-1, -4], [-1, -5], [-1, -6]]})
	world.apply_server_event({"kind": "building_created", "building_kind": "farm", "owner": "alice", "object_id": "f1", "cells": [[6, 4], [7, 4], [6, 5], [7, 5]]})
	world.apply_server_event({"kind": "road_changed", "cells": [[5, 4], [5, 5], [4, 5], [3, 5], [2, 4]]})
	world.apply_server_event({"kind": "building_created", "building_kind": "factory", "owner": "bob", "object_id": "fa", "cells": [[-9, 1], [-8, 1], [-7, 1], [-9, 2], [-8, 2], [-7, 2]]})
	world.apply_server_event({"kind": "building_created", "building_kind": "shop", "owner": "alice", "object_id": "s1", "cells": [[4, -9], [5, -9], [4, -8], [5, -8]]})
	world.apply_server_event({"kind": "building_created", "building_kind": "warehouse", "owner": "bob", "object_id": "w1", "cells": [[-9, -8], [-8, -8], [-7, -8], [-9, -7], [-8, -7], [-7, -7], [-9, -6], [-8, -6], [-7, -6]]})
	world.apply_server_event({"kind": "building_created", "building_kind": "mine", "owner": "npc:x", "object_id": "m1", "cells": [[8, -4], [9, -4], [8, -3], [9, -3], [8, -2], [9, -2]]})
	world.apply_server_event({"kind": "building_created", "building_kind": "park", "owner": "city", "object_id": "p1", "cells": [[-6, 6], [-5, 6], [-6, 7], [-5, 7]]})
	world.focus_cell(Vector2i(0, 0))
	world.target_size = 38.0
	world.camera.size = 38.0
	world._sync_camera()
	world._update_visible_chunks()
	world.flush_all()
	for k in 6:
		await process_frame
	get_root().get_texture().get_image().save_png(out_dir.path_join("world3d_ufa.png"))
	world.target_size = 80.0
	world.camera.size = 80.0
	world._sync_camera()
	world._update_visible_chunks()
	world.flush_all()
	for k in 6:
		await process_frame
	get_root().get_texture().get_image().save_png(out_dir.path_join("world3d_far.png"))
	world.focus_cell(Vector2i(load("res://road_network.gd").river_x(20), 20))
	world.target_size = 40.0
	world.camera.size = 40.0
	world._sync_camera()
	world._update_visible_chunks()
	world.flush_all()
	for k in 6:
		await process_frame
	get_root().get_texture().get_image().save_png(out_dir.path_join("world3d_river.png"))
	print("SCREENSHOTS_SAVED ", out_dir)
	quit(0)
