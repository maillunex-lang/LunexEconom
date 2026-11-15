extends SceneTree
const TRAFFIC = preload("res://world3d/road_traffic.gd")
const ROADS = preload("res://road_network.gd")

func _initialize() -> void:
	call_deferred("_run")

func _check(ok: bool, reason: String) -> void:
	if not ok:
		push_error("ROAD_TRAFFIC_SMOKE_FAIL " + reason)
		quit(1)

func _run() -> void:
	var road_network = ROADS.new()
	var traffic = TRAFFIC.new()
	root.add_child(traffic)
	traffic.configure(road_network)
	traffic.refresh_around(Vector2i.ZERO)
	_check(traffic.vehicles.size() > 0, "no vehicles on base crossroads")
	_check(traffic.vehicles.size() <= traffic.MAX_VEHICLES, "vehicle budget exceeded")
	var first: Dictionary = traffic.vehicles[0]
	var path: Array[Vector2i] = first["path"]
	_check(path.size() >= 4, "route too short")
	for i in range(1, path.size()):
		_check(absi(path[i].x - path[i-1].x) + absi(path[i].y - path[i-1].y) == 1, "non-connected route")
	var before: Vector3 = first["node"].position
	traffic._update_positions(0.1)
	_check(first["node"].position.distance_to(before) > 0.01, "vehicle not moving")
	traffic.refresh_around(Vector2i.ZERO)
	_check(traffic.vehicles.size() <= traffic.MAX_VEHICLES, "refresh duplicated vehicles")
	traffic.clear_vehicles()
	_check(traffic.vehicles.is_empty(), "clear did not release vehicle references")
	print("ROAD_TRAFFIC_SMOKE_PASS bounded/connected/moving/refresh")
	quit(0)