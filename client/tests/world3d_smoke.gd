extends SceneTree
## Headless check of the 2.5D world inside the real game screen: camera, ground chunks with the river, crossroads and trees, buildings
## from server events with their real footprints (GLB or procedural), ray picking, panning, zoom, the construction preview, the season
## refresh and the performance overlay. Always quits.

var failures := 0

func _initialize() -> void:
	call_deferred("_run")

func _check(condition: bool, label: String) -> void:
	if not condition:
		failures += 1
		print("FAIL: ", label)

func _run() -> void:
	var host: Control = load("res://world.tscn").instantiate()
	get_root().add_child(host)
	await process_frame
	await process_frame
	var world = host.world
	_check(world is Node3D, "the world is 3D")
	_check(world.camera is Camera3D and world.camera.projection == Camera3D.PROJECTION_ORTHOGONAL, "isometric orthographic camera")
	_check(world.camera.current, "the world camera is the active one")
	world.flush_all()
	_check(world.active_chunks.size() > 0, "visible chunks are created")
	_check(world.active_chunks.has(Vector2i(0, 0)), "the chunk of Ufa's crossroads is visible at start")
	var ground = world.active_chunks[Vector2i(0, 0)].get_node_or_null("Ground")
	_check(ground is MeshInstance3D and ground.mesh != null and ground.mesh.get_surface_count() == 1, "ground mesh of a chunk")

	# terrain rules are the server's: crossroads in the centre, no water in the city, the river far away
	_check(world.cell_kind(0, 0) == 3 and world.cell_kind(4, 0) == 3 and world.cell_kind(0, -4) == 3, "Ufa crossroads are roads")
	_check(world.cell_kind(19, 7) != 3, "no old road grid")
	var water := 0
	for x in range(-40, 41):
		for y in range(-40, 41):
			if world.cell_kind(x, y) == 4:
				water += 1
	_check(water == 0, "no water in Ufa")
	var rx: int = load("res://road_network.gd").river_x(10)
	_check(world.cell_kind(rx, 10) == 4, "the river")

	# a server snapshot and events: a 1x3 house, a 2x2 farm, a 3x2 factory (GLB), a road
	world.apply_server_event({"kind": "building_created", "building_kind": "house", "owner": "town:ufa", "object_id": "h13", "cells": [[6, 6], [6, 7], [6, 8]]})
	world.apply_server_event({"kind": "building_created", "building_kind": "farm", "owner": "alice", "object_id": "f1", "cells": [[2, 2], [3, 2], [2, 3], [3, 3]]})
	world.apply_server_event({"kind": "building_created", "building_kind": "factory", "owner": "bob", "object_id": "fa1", "cells": [[-6, 2], [-5, 2], [-4, 2], [-6, 3], [-5, 3], [-4, 3]]})
	world.apply_server_event({"kind": "road_changed", "object_id": "f1", "owner": "alice", "cells": [[1, 1], [1, 2]]})
	world.flush_all()
	_check(world.building_nodes.size() == 3, "one 3D node per building, not per cell: %d" % world.building_nodes.size())
	var house: Node3D = world.building_nodes.get("h13")
	_check(house != null and house.position.is_equal_approx(Vector3(12.0, 0.0, 14.0)), "the 1x3 house stands in the middle of its plot")
	_check(house != null and house.get_node_or_null("OwnerFlag") == null, "town houses carry no owner flag")
	var farm: Node3D = world.building_nodes.get("f1")
	_check(farm != null and farm.get_node_or_null("OwnerFlag") != null, "player buildings carry the owner's flag")
	var factory: Node3D = world.building_nodes.get("fa1")
	_check(factory != null and factory.get_child_count() > 1, "the factory has a 3D model")
	_check(load("res://world3d/building_models.gd").model_path("factory", 3, 2).is_empty(), "untextured prototype GLBs are not used")
	_check(world.cell_kind(1, 2) == 3, "the access road arrived")
	_check(world.building_info(Vector2i(6, 7)).get("kind", "") == "house", "building card data")
	world.apply_server_event({"kind": "building_removed", "object_id": "f1", "cells": [[2, 2], [3, 2], [2, 3], [3, 3]]})
	world.flush_all()
	_check(not world.building_nodes.has("f1"), "a sold building disappears")
	world.apply_chunk_snapshot(Vector2i(0, 0), [{"x": 6, "y": 6, "kind": "building_created", "building_kind": "house", "object_id": "h13", "owner": "town:ufa"}])
	world.flush_all()
	_check(world.building_nodes.has("h13") and world.building_nodes.has("fa1"), "a snapshot replaces only its own chunk")

	# every kind gets a visual of the right footprint
	for kind in ["farm", "mine", "factory", "warehouse", "shop", "school", "hospital", "park", "house"]:
		var node: Node3D = load("res://world3d/building_models.gd").make(kind, 2, 3, "x", "")
		_check(node.get_child_count() > 0 and float(node.get_meta("top", 0.0)) > 0.0, "a visual for " + kind)
		node.free()

	# picking: the screen centre is the focus cell; a tap selects it
	var centre: Vector2 = host.get_viewport().get_visible_rect().size * 0.5
	world.focus_cell(Vector2i(10, -5))
	_check(world.screen_cell(centre) == Vector2i(10, -5), "the ray through the screen centre hits the focus cell: " + str(world.screen_cell(centre)))
	world.select_screen(centre)
	_check(world.selected == Vector2i(10, -5), "a tap selects the cell")
	# +x goes right-down on screen like the old map
	var p0: Vector2 = world.camera.unproject_position(world.cell_center(Vector2i(10, -5)))
	var px: Vector2 = world.camera.unproject_position(world.cell_center(Vector2i(11, -5)))
	var py: Vector2 = world.camera.unproject_position(world.cell_center(Vector2i(10, -4)))
	_check(px.x > p0.x and px.y > p0.y and py.x < p0.x and py.y > p0.y, "isometric orientation")

	# panning follows the finger; zoom is clamped
	var before: Vector3 = world.target_focus
	world._pan_pixels(Vector2(100, 0))
	var moved_cell: Vector2i = world.cell_of(world.target_focus)
	_check(world.target_focus != before, "a drag pans")
	world.focus = world.target_focus
	world._sync_camera()
	var under: Vector2 = world.camera.unproject_position(world.cell_center(Vector2i(10, -5)))
	_check(under.x > centre.x + 60.0, "the map moves with the finger (content goes right)")
	world.set_zoom(1.0)
	_check(world.target_size == world.MIN_SIZE, "zoom in is clamped")
	world.set_zoom(10000.0)
	_check(world.target_size == world.MAX_SIZE, "zoom out is clamped")

	# construction preview of a farm next to the crossroads
	world.focus_cell(Vector2i(0, 0))
	world.choose_build("farm")
	world.select_cell(Vector2i(1, -3))
	var preview: Dictionary = world.preview_build(Vector2i(1, -3))
	_check(bool(preview.get("ok", false)), "a farm by the crossroads can be placed: " + str(preview))
	_check(world._preview_node.mesh != null, "the preview footprint is drawn")
	world.choose_build("farm")
	world.select_cell(Vector2i(rx, 10))
	_check(not bool(world.preview_build(Vector2i(rx, 10)).get("ok", true)), "no building on the river")
	world.cancel_build()
	_check(world._preview_node.mesh == null, "cancel removes the preview")

	# zones: once the server says they exist, a factory is refused in the city centre and the preview explains why
	world.set_zones({"enabled": true, "cities": [{"id": "ufa", "x": 0, "y": 0, "radius": 63, "wedge_angle": 90}]})
	world.choose_build("factory")
	world.select_cell(Vector2i(-8, -8))
	var zone_preview: Dictionary = world.preview_build(Vector2i(-8, -8))
	_check(str(zone_preview.get("reason", "")) == "wrong_zone" and str(zone_preview.get("message", "")).contains("центр города"), "a factory in the centre: " + str(zone_preview))
	world.cancel_build()
	world.set_zones({"enabled": false, "cities": []})

	# season refresh and the performance overlay keep working
	host._toggle_seasons()
	world._read_season()
	world.flush_all()
	host._toggle_seasons()
	host._toggle_fps()
	host.perf_overlay.refresh()
	_check(host.perf_overlay.output.text.contains("Чанки"), "performance overlay")
	host._toggle_fps()

	# moving to another city
	host.goto_geo_city({"x": -3, "y": 373, "name": "Стерлитамак"})
	world.flush_all()
	_check(world.cell_of(world.focus) == Vector2i(-3, 373), "the camera moves to the city")
	_check(world.active_chunks.has(Vector2i(-1, 31)), "the city's chunks are created")
	_check(world.cell_kind(-3, 373) == 3, "Sterlitamak crossroads")

	host.queue_free()
	await process_frame
	if failures == 0:
		print("WORLD3D_SMOKE_PASS terrain/buildings/picking/pan/zoom/preview/seasons/overlay/travel")
		quit(0)
	else:
		print("WORLD3D_SMOKE_FAIL ", failures)
		quit(1)
