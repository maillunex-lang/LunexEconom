extends SceneTree
## Headless check of the generated city: the client street predicate equals the server's (cell for cell on samples), the house lots chosen by the
## server never sit on a client-drawn street, and server houses arrive as buildings the client can draw and describe. Always quits.
## The PARITY table is produced from server/citygen.py (regenerate it with the snippet in docs/CITYGEN.md if the city layout rules change).

const PARITY := {"ufa":{"city":{"id":"ufa","x":0,"y":0,"radius":63,"specialization":"управление, нефтехимия"},"street":[[-60,-18],[-60,4],[-57,-18],[-57,4],[-57,26],[-54,-18],[-54,4],[-54,26],[-51,-18],[-51,4],[-51,26],[-48,-40],[-48,-38],[-48,-36],[-48,-34],[-48,-32],[-48,-30],[-48,-28],[-48,-26],[-48,-24],[-48,-22],[-48,-20],[-48,-18],[-48,-16],[-48,-14],[-48,-12],[-48,-10],[-48,-8],[-48,-6],[-48,-4],[-48,-2],[-48,0],[-48,2],[-48,4],[-48,6],[-48,8],[-48,10],[-48,12],[-48,14],[-48,16],[-48,18],[-48,20],[-48,22],[-48,24],[-48,26],[-48,28],[-48,30],[-48,32],[-48,34],[-48,36]],"other":[[-66,-66],[-66,-64],[-66,-62],[-66,-60],[-66,-58],[-66,-56],[-66,-54],[-66,-52],[-66,-50],[-66,-48],[-66,-46],[-66,-44],[-66,-42],[-66,-40],[-66,-38],[-66,-36],[-66,-34],[-66,-32],[-66,-30],[-66,-28],[-66,-26],[-66,-24],[-66,-22],[-66,-20],[-66,-18],[-66,-16],[-66,-14],[-66,-12],[-66,-10],[-66,-8],[-66,-6],[-66,-4],[-66,-2],[-66,0],[-66,2],[-66,4],[-66,6],[-66,8],[-66,10],[-66,12],[-66,14],[-66,16],[-66,18],[-66,20],[-66,22],[-66,24],[-66,26],[-66,28],[-66,30],[-66,32]],"lots":[[8,1],[-8,5],[1,8],[-3,-10],[-9,-6],[-6,-11],[-3,10],[-2,-13],[4,-12],[1,-13]]},"sterlitamak":{"city":{"id":"sterlitamak","x":-3,"y":373,"radius":35,"specialization":"химия, машиностроение"},"street":[[-35,379],[-32,357],[-32,379],[-29,357],[-29,379],[-26,357],[-26,379],[-23,357],[-23,379],[-23,401],[-20,357],[-20,379],[-20,401],[-17,357],[-17,365],[-17,379],[-17,401],[-14,357],[-14,365],[-14,379],[-14,401],[-11,365],[-11,379],[-11,401],[-8,339],[-8,341],[-8,343],[-8,345],[-8,347],[-8,349],[-8,351],[-8,353],[-8,355],[-8,357],[-8,359],[-8,361],[-8,363],[-8,365],[-8,367],[-8,369],[-8,371],[-8,373],[-8,375],[-8,377],[-8,379],[-8,381],[-8,383],[-8,385],[-8,387],[-8,389]],"other":[[-41,335],[-41,337],[-41,339],[-41,341],[-41,343],[-41,345],[-41,347],[-41,349],[-41,351],[-41,353],[-41,355],[-41,357],[-41,359],[-41,361],[-41,363],[-41,365],[-41,367],[-41,369],[-41,371],[-41,373],[-41,375],[-41,377],[-41,379],[-41,381],[-41,383],[-41,385],[-41,387],[-41,389],[-41,391],[-41,393],[-41,395],[-41,397],[-41,399],[-41,401],[-41,403],[-41,405],[-41,407],[-41,409],[-41,411],[-38,335],[-38,337],[-38,339],[-38,341],[-38,343],[-38,345],[-38,347],[-38,349],[-38,351],[-38,353],[-38,355]],"lots":[[-3,369],[-7,370],[-7,375],[-7,377],[-4,366],[-10,377],[-5,380],[-12,370],[4,370],[-11,366]]},"baymak":{"city":{"id":"baymak","x":453,"y":717,"radius":15,"specialization":"агро, добыча"},"street":[[441,713],[444,713],[447,719],[450,711],[450,713],[450,715],[450,717],[450,719],[450,721],[450,723],[453,719],[456,719],[459,719],[462,713],[465,713],[468,717]],"other":[[435,699],[435,701],[435,703],[435,705],[435,707],[435,709],[435,711],[435,713],[435,715],[435,717],[435,719],[435,721],[435,723],[435,725],[435,727],[435,729],[435,731],[435,733],[435,735],[438,699],[438,701],[438,703],[438,705],[438,707],[438,709],[438,711],[438,713],[438,715],[438,717],[438,719],[438,721],[438,723],[438,725],[438,727],[438,729],[438,731],[438,733],[438,735],[441,699],[441,701],[441,703],[441,705],[441,707],[441,709],[441,711],[441,715],[441,717],[441,719],[441,721],[441,723]],"lots":[[452,720],[454,720],[448,720],[458,717],[451,722],[453,710],[446,714],[445,717],[458,720],[447,710]]}}

var failures := 0

func _initialize() -> void:
	call_deferred("_run")

func _check(condition: bool, label: String) -> void:
	if not condition:
		failures += 1
		print("FAIL: ", label)

func _run() -> void:
	var layout = load("res://city_layout.gd")
	for id in PARITY:
		var entry: Dictionary = PARITY[id]
		var city: Dictionary = entry["city"]
		for cell in entry["street"]:
			_check(layout.visual_at(city, int(cell[0]), int(cell[1]), 0) == "street", "%s street at %s" % [id, str(cell)])
		for cell in entry["other"]:
			_check(layout.visual_at(city, int(cell[0]), int(cell[1]), 0) != "street", "%s not a street at %s" % [id, str(cell)])
		for lot in entry["lots"]:
			for dx in range(2):
				for dy in range(2):
					_check(layout.visual_at(city, int(lot[0]) + dx, int(lot[1]) + dy, 0) != "street", "%s lot %s cell is not a street" % [id, str(lot)])

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
	# the renderer can draw it (several different positions, so every colour variant runs)
	var renderer = load("res://chunk_renderer.gd").new()
	get_root().add_child(renderer)
	var drawn := [0]
	renderer.draw.connect(func() -> void:                       # drawing is only legal while the node is being drawn
		for i in range(8):
			renderer._draw_house(Vector2(13.0 * i, 7.0 * i))
			drawn[0] += 1
	)
	renderer.queue_redraw()
	await process_frame
	await process_frame
	_check(drawn[0] >= 8, "all house colour variants were drawn without errors")
	if failures == 0:
		print("CITYGEN_SMOKE_PASS")
	else:
		print("CITYGEN_SMOKE_FAILED ", failures)
	quit(1 if failures > 0 else 0)
