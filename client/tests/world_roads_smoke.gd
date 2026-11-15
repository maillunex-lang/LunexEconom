extends SceneTree
const Roads = preload("res://world/roads.gd")
func _initialize() -> void:
    call_deferred("_run")
func _run() -> void:
    var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string("res://tests/vectors_roads_world_v1.json"))
    assert(parsed is Dictionary)
    var data: Dictionary = parsed
    var cities: Array = data.get("cities",[])
    assert(cities.size()==20)
    var edges: Array = Roads.trunk_edges(cities)
    assert(edges.size()==19)
    for i in range(edges.size()):
        assert(str(edges[i][0]) == str(data["edges"][i][0]) and str(edges[i][1]) == str(data["edges"][i][1]) and int(edges[i][2]) == int(data["edges"][i][2]),"MST discrepancy at edge %d" % i)
    for sample in data["samples"]:
        for city in cities:
            if city["id"]=="ufa":
                city["level"] = int(sample.get("level",1))
                break
        assert(Roads.virtual_road(int(sample["x"]),int(sample["y"]),cities,edges) == bool(sample["road"]),
            "road disagreement at %d,%d level %d" % [sample["x"],sample["y"],sample.get("level",1)])
        assert(Roads.authoritative_zone(int(sample["x"]),int(sample["y"]),cities)==str(sample["zone"]),
            "zone disagreement at %d,%d" % [sample["x"],sample["y"]])
    print("world roads smoke OK: 19 MST edges, ",data["samples"].size()," server-derived road/zone samples")
    quit(0)
