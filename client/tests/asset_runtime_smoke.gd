extends SceneTree
## Standalone GLB runtime acceptance: model lookup, instancing and geometry.
const BuildingModels = preload("res://world3d/building_models.gd")
const CASES := [
	["truck", 2, 3],
	["tractor", 2, 2],
	["construction_foundation", 3, 2],
	["construction_frame", 3, 2],
	["road_corner", 1, 1],
	["grain_field", 3, 2],
	["oil_well", 2, 2],
]
var failed := 0

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	for item in CASES:
		var kind: String = item[0]
		var w: int = item[1]
		var h: int = item[2]
		var info: Dictionary = BuildingModels.model_path(kind, w, h, "qa")
		if info.is_empty():
			push_error("GLB missing from runtime lookup: " + kind)
			failed += 1
			continue
		var node: Node3D = BuildingModels.make(kind, w, h, "qa")
		root.add_child(node)
		var top: float = float(node.get_meta("top", 0.0))
		var model := node.get_node_or_null("Model")
		if model == null or top <= 0.0:
			push_error("GLB not instantiated or invalid top: " + kind)
			failed += 1
		node.queue_free()
	if failed == 0:
		print("ASSET_RUNTIME_SMOKE_PASS count=", CASES.size())
	quit(0 if failed == 0 else 2)
