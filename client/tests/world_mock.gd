extends Node
## Deterministic in-process HTTP stand-in, including conditional requests.
const Gen = preload("res://world/generator.gd")
var calls: Array[String] = []
var buy_ids: Array[String] = []
var failures_before_buy := 0
var not_modified := 0
var bought: Dictionary = {}
var versions: Dictionary = {}
var growth_events: Array = []
var cities: Array = []
var requests_in_flight := 0
var max_parallel := 0

func _ready() -> void:
    var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string("res://tests/cities_world_seed_v1.json"))
    assert(parsed is Dictionary)
    cities = parsed.get("cities", [])
    for i in range(cities.size()):
        cities[i]["level"] = 1
        cities[i]["radius"] = 12
        cities[i]["center"] = {"x":cities[i]["x"],"y":cities[i]["y"]}

func _args(path: String) -> Dictionary:
    var output := {}
    if not path.contains("?"):
        return output
    for part in path.get_slice("?",1).split("&"):
        var parts := part.split("=")
        if parts.size() == 2:
            output[parts[0]] = parts[1]
    return output

func respond(path: String, method: int, data: Dictionary, headers: PackedStringArray) -> Dictionary:
    calls.append(path)
    requests_in_flight += 1
    max_parallel = maxi(requests_in_flight, max_parallel)
    await get_tree().process_frame
    requests_in_flight -= 1
    if path == "/world/cities":
        return {"code":200,"data":{"cities":cities,"seed":Gen.SEED}}
    if path.begins_with("/world/events"):
        var after := int(_args(path).get("after",0))
        var items := growth_events.filter(func(x: Dictionary): return int(x.get("version",0)) > after)
        return {"code":200,"data":{"events":items,"next_after":int(items[-1]["version"]) if not items.is_empty() else after}}
    if path.begins_with("/world/chunk"):
        var args := _args(path)
        var cx := int(args.get("cx",0))
        var cy := int(args.get("cy",0))
        var key := "%d,%d" % [cx,cy]
        var version := int(versions.get(key,0))
        var etag := '"world-v1-%d-%d-%d"' % [cx,cy,version]
        if headers.has("If-None-Match: " + etag):
            not_modified += 1
            return {"code":304,"data":{},"etag":etag}
        return {"code":200,"data":_chunk(cx,cy,version,etag),"etag":etag}
    if path.begins_with("/land/parcels"):
        var arg: String = str(_args(path).get("chunk","0,0"))
        var cx := int(arg.get_slice(",",0))
        var cy := int(arg.get_slice(",",1))
        var output: Array = []
        for dy in range(2):
            for dx in range(2):
                var px := cx*2+dx
                var py := cy*2+dy
                var parcel := {"px":px,"py":py,"zone":"residential","price":15000,"owner_kind":"state","owner_ref":"state"}
                if bought.has("%d,%d" % [px,py]):
                    parcel["owner_kind"] = "player"
                    parcel["owner_ref"] = "1"
                output.append(parcel)
        return {"code":200,"data":{"parcels":output}}
    if path == "/land/buy" and method == HTTPClient.METHOD_POST:
        buy_ids.append(str(data.get("request_id","")))
        if failures_before_buy > 0:
            failures_before_buy -= 1
            return {"code":0,"data":{}}
        var key := "%d,%d" % [int(data.get("px",0)),int(data.get("py",0))]
        if bought.has(key):
            if bought[key] == data["request_id"]:
                return {"code":200,"data":{"px":data["px"],"py":data["py"],"idempotent":true}}
            return {"code":409,"data":{"error":"parcel_unavailable"}}
        bought[key] = data["request_id"]
        return {"code":201,"data":{"px":data["px"],"py":data["py"],"idempotent":false}}
    return {"code":404,"data":{"error":"not_found"}}

func _chunk(cx: int,cy: int,version: int,etag: String) -> Dictionary:
    var terrain: Array = []
    var zones: Array = []
    var roads: Array = []
    for dy in range(12):
        var t: Array = []
        var z: Array = []
        var r: Array = []
        for dx in range(12):
            var x := cx*12+dx
            var y := cy*12+dy
            t.append(Gen.terrain(Gen.SEED,x,y))
            z.append(Gen.zone(x,y,0,0,12,1))
            r.append(x == 0 or y == 0)
        terrain.append(t)
        zones.append(z)
        roads.append(r)
    return {"cx":cx,"cy":cy,"terrain":terrain,"zones":zones,"roads":roads,"version":version,"etag":etag}
