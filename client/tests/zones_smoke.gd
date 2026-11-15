extends SceneTree
## The client zone rules equal the server's (samples produced by server/zoning.py) and refuse a factory in the city centre. Always quits.
func _initialize() -> void:
	var text := FileAccess.get_file_as_string("res://tests/zone_samples.json")
	var data: Dictionary = JSON.parse_string(text)
	var zones = load("res://zones.gd").new()
	zones.load_data(data)
	var wrong := 0
	for sample in data["samples"]:
		if zones.zone_at(int(sample[0]), int(sample[1])) != str(sample[2]):
			wrong += 1
			print("MISMATCH ", sample, " got ", zones.zone_at(int(sample[0]), int(sample[1])))
	var centre: Array = [Vector2i(0, 0), Vector2i(1, 0), Vector2i(0, 1)]
	var refused: String = zones.refusal("factory", centre)
	var ok_house: String = zones.refusal("house", centre)
	if wrong == 0 and refused.contains("центр города") and ok_house == "" and zones.refusal("shop", centre) == "":
		print("ZONES_SMOKE_PASS parity/refusal")
		quit(0)
	else:
		print("ZONES_SMOKE_FAIL wrong=", wrong, " refused=", refused)
		quit(1)
