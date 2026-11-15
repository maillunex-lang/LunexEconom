extends Node3D
## Decorative traffic only. Roads and routes come from the existing server-synced road graph.
## Never changes road cells, buildings, player balance or server state.
const MODELS = preload("res://world3d/building_models.gd")
const ROAD_SCRIPT = preload("res://road_network.gd")
const CELL := 2.0
const MAX_VEHICLES := 5
const SPEED := 1.45
const MAX_ROUTE := 14

var network
var vehicles: Array[Dictionary] = []
var enabled := true

func configure(road_network) -> void:
	network = road_network

func clear_vehicles() -> void:
	for v in vehicles:
		if is_instance_valid(v["node"]):
			v["node"].queue_free()
	vehicles.clear()

func refresh_around(center: Vector2i) -> void:
	clear_vehicles()
	if network == null or not enabled:
		return
	var starts: Array[Vector2i] = []
	for y in range(center.y - 8, center.y + 9):
		for x in range(center.x - 8, center.x + 9):
			var cell := Vector2i(x, y)
			if network.is_road(cell) and network.neighbors(cell).size() >= 2:
				starts.append(cell)
	starts.sort_custom(func(a: Vector2i, b: Vector2i) -> bool:
		var da := absi(a.x - center.x) + absi(a.y - center.y)
		var db := absi(b.x - center.x) + absi(b.y - center.y)
		return da < db if da != db else (a.y < b.y if a.y != b.y else a.x < b.x))
	for i in range(mini(starts.size(), MAX_VEHICLES * 3)):
		if vehicles.size() >= MAX_VEHICLES:
			break
		var start: Vector2i = starts[i]
		var path := _walk(start, i)
		if path.size() < 4:
			continue
		var kind := "truck" if i % 2 == 0 else "tractor"
		var model: Node3D = MODELS.make(kind, 2, 3 if kind == "truck" else 2, "traffic_%d" % i)
		model.name = "Traffic_%d" % i
		model.scale = Vector3.ONE * 0.30
		add_child(model)
		vehicles.append({"node": model, "path": path, "distance": float(i) * 0.55, "speed": SPEED * (0.8 + 0.1 * float(i % 3))})
	_update_positions(0.0)

func _walk(start: Vector2i, seed: int) -> Array[Vector2i]:
	var result: Array[Vector2i] = [start]
	var previous := Vector2i(2147483647, 2147483647)
	var current := start
	for step in range(MAX_ROUTE - 1):
		var choices: Array[Vector2i] = network.neighbors(current)
		choices.erase(previous)
		if choices.is_empty():
			break
		choices.sort_custom(func(a: Vector2i, b: Vector2i) -> bool:
			return a.y < b.y if a.y != b.y else a.x < b.x)
		var next: Vector2i = choices[(seed + step / 4) % choices.size()]
		previous = current
		current = next
		result.append(current)
	return result

func _process(delta: float) -> void:
	if enabled and visible:
		_update_positions(minf(delta, 0.1))

func _update_positions(delta: float) -> void:
	for v in vehicles:
		var path: Array[Vector2i] = v["path"]
		var distance: float = fposmod(float(v["distance"]) + delta * float(v["speed"]), float(path.size() - 1))
		v["distance"] = distance
		var index := mini(int(distance), path.size() - 2)
		var fraction := distance - float(index)
		var a := Vector3(float(path[index].x) * CELL, 0.12, float(path[index].y) * CELL)
		var b := Vector3(float(path[index + 1].x) * CELL, 0.12, float(path[index + 1].y) * CELL)
		var node: Node3D = v["node"]
		node.position = a.lerp(b, fraction)
		node.rotation.y = atan2(b.x - a.x, b.z - a.z)