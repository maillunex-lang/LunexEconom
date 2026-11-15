extends SceneTree
## Headless check of the generated city: the client terrain rules (city crossroads, the river, noise) equal the server's on samples, and server
## houses arrive as buildings the client can draw and describe. Always quits.
## The tables are produced from server/roads.py (regenerate them with the snippet in docs/CITYGEN.md if the terrain rules change).

const RIVER := [[-700, 219], [-129, 212], [-64, 229], [-1, 221], [0, 221], [1, 221], [63, 248], [64, 249], [65, 248], [373, 234], [500, 216], [1000, 237], [9999, 236]]
const BASE := [[0, 4, true], [-4, 0, true], [-3, 373, true], [-12, 457, true], [520, 680, true], [0, 5, false], [19, 7, false], [5, 5, false]]
const WATER := [[219, -5, false], [221, -5, true], [222, -5, true], [223, -5, false], [236, 100, false], [238, 100, true], [239, 100, true], [240, 100, false], [246, 300, false], [248, 300, true], [249, 300, true], [250, 300, false]]
const NOISE := [[3, 4, 32], [-77, 901, 24], [1234, -5678, 94], [0, 0, 35]]

var failures := 0

func _initialize() -> void:
	call_deferred("_run")

func _check(condition: bool, label: String) -> void:
	if not condition:
		failures += 1
		print("FAIL: ", label)

func _run() -> void:
	var road_rules = load("res://road_network.gd")
	for item in RIVER:
		_check(road_rules.river_x(int(item[0])) == int(item[1]), "river_x(%d)" % int(item[0]))
	for item in BASE:
		_check(road_rules.is_base_road(Vector2i(int(item[0]), int(item[1]))) == bool(item[2]), "base road at " + str(item))
	for item in WATER:
		_check(road_rules.is_water(Vector2i(int(item[0]), int(item[1]))) == bool(item[2]), "water at " + str(item))
	for item in NOISE:
		_check(road_rules.terrain_noise(int(item[0]), int(item[1])) == int(item[2]), "noise at " + str(item))
	_check(road_rules.CITY_CENTERS.size() == 20, "twenty city crossroads")

	# a server snapshot with a generated house: the client treats it as a building and names its owner
	var world: Control = load("res://world.tscn").instantiate()
	get_root().add_child(world)
	await process_frame
	await process_frame
	var cells := [[40, 40], [40, 41], [41, 40], [41, 41]]
	world.world.apply_server_event({"kind": "building_created", "building_kind": "house", "owner": "town:ufa", "object_id": "h1", "cells": cells})
	_check(world.world.cell_kind(40, 40) == 6, "a house cell is a building cell")
	_check(world.world.building_at(Vector2i(41, 41)) == "house", "building_at reports the house")
	var info: Dictionary = world.world.building_info(Vector2i(40, 41))
	_check(str(info.get("owner", "")) == "town:ufa" and str(info.get("kind", "")) == "house", "building_info owner and kind")
	_check(world.KIND_NAMES.has("house"), "the card has a name for a house")
	_check(world._owner_name("town:ufa").begins_with("город"), "owner is shown as the town: " + world._owner_name("town:ufa"))
	# a snapshot (what /chunk returns) works the same way
	world.world.apply_chunk_snapshot(Vector2i(10, 10), [{"x": 120, "y": 120, "kind": "building_created", "building_kind": "house", "object_id": "h2", "owner": "town:ufa"}])
	_check(world.world.building_at(Vector2i(120, 120)) == "house", "snapshot house is known")
	# the 3D world builds one house node per object, whatever the footprint (1x1, 1x2, 1x3)
	world.world.apply_server_event({"kind": "building_created", "building_kind": "house", "owner": "town:ufa", "object_id": "h3", "cells": [[44, 40], [44, 41], [44, 42]]})
	world.world.flush_all()
	_check(world.world.building_nodes.has("h1") and world.world.building_nodes.has("h2") and world.world.building_nodes.has("h3"), "3D house nodes")
	if failures == 0:
		print("CITYGEN_SMOKE_PASS")
	else:
		print("CITYGEN_SMOKE_FAILED ", failures)
	quit(1 if failures > 0 else 0)
