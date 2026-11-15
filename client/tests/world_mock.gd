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
var road_cells: Dictionary = {}
var road_posts: Array = []
var built: Dictionary = {}
var build_requests: Dictionary = {}
var cash := 99999999
const BUILDING_CATALOG := [
    {"id":"field","name":"Поле","description":"Выращивание зерна","category":"farm","zones":["free","industrial"],"size":{"width":2,"height":2},"build_cost":150000,"build_days":1},
    {"id":"mill","name":"Мельница","description":"Помол зерна","category":"factory","zones":["industrial"],"size":{"width":2,"height":2},"build_cost":250000,"build_days":1},
    {"id":"bakery","name":"Пекарня","description":"Выпечка хлеба","category":"factory","zones":["industrial"],"size":{"width":2,"height":2},"build_cost":300000,"build_days":1}
]
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
    if path == "/catalog":
        return {"code":200,"etag":"test-polish","data":{"version":"test-polish","products":[],"recipes":[],"buildings":BUILDING_CATALOG}}
    if path == "/ledger/balance":
        return {"code":200,"data":{"balance":cash}}
    if path == "/enterprises" and method == HTTPClient.METHOD_POST:
        var parcel_key := "%d,%d" % [int(data.get("px",-999)),int(data.get("py",-999))]
        if not bought.has(parcel_key):
            return {"code":409,"data":{"error":"parcel_not_owned"}}
        var building: Dictionary = {}
        for entry in BUILDING_CATALOG:
            if entry["id"]==str(data.get("building_id","")):
                building=entry
        if building.is_empty():
            return {"code":404,"data":{"error":"unknown_building"}}
        var x := int(data.get("x",0))
        var y := int(data.get("y",0))
        var width := int(building["size"]["width"])
        var height := int(building["size"]["height"])
        if x<int(data["px"])*6 or y<int(data["py"])*6 or x+width>int(data["px"])*6+6 or y+height>int(data["py"])*6+6:
            return {"code":409,"data":{"error":"outside_parcel"}}
        for cy in range(y,y+height):
            for cx in range(x,x+width):
                if Gen.zone(cx,cy,0,0,12,1) not in building["zones"]:
                    return {"code":409,"data":{"error":"invalid_zone"}}
                if Gen.terrain(Gen.SEED,cx,cy)=="water":
                    return {"code":409,"data":{"error":"water"}}
                if _has_road(cx,cy):
                    return {"code":409,"data":{"error":"road_overlap"}}
        var access := false
        for cy in range(y,y+height):
            for cx in range(x,x+width):
                for near in [Vector2i(cx-1,cy),Vector2i(cx+1,cy),Vector2i(cx,cy-1),Vector2i(cx,cy+1)]:
                    if near.x>=x and near.x<x+width and near.y>=y and near.y<y+height:
                        continue
                    if _has_road(near.x,near.y):
                        access = true
        if not access:
            return {"code":409,"data":{"error":"no_road_access"}}
        if cash<int(building["build_cost"])*300/1000:
            return {"code":409,"data":{"error":"insufficient_funds"}}
        var request_id := str(data.get("request_id",""))
        if build_requests.has(request_id):
            return {"code":200,"data":{"id":build_requests[request_id],"idempotent":true}}
        var id := built.size()+1
        built[id]={"id":id,"x":x,"y":y,"width":width,"height":height,"name":building["name"],"building_id":building["id"],"stage_index":0}
        build_requests[request_id]=id
        cash-=int(building["build_cost"])*300/1000
        for cy in range(y,y+height):
            for cx in range(x,x+width):
                var key := "%d,%d" % [Gen.floor_div(cx,12),Gen.floor_div(cy,12)]
                versions[key] = int(versions.get(key,0))+1
        return {"code":201,"data":{"id":id}}
    if path == "/enterprises":
        return {"code":200,"data":{"enterprises":built.keys()}}
    if path.begins_with("/enterprises/"):
        var id := int(path.get_slice("/",2))
        if built.has(id):
            return {"code":200,"data":built[id]}
        return {"code":404,"data":{"error":"not_found"}}
    if path == "/world/roads" and method == HTTPClient.METHOD_POST:
        var cells: Array = data.get("cells",[])
        if cells.is_empty():
            return {"code":400,"data":{"error":"invalid_road_cells"}}
        var requested := {}
        var connection := false
        for cell in cells:
            var cx := int(cell[0])
            var cy := int(cell[1])
            requested["%d,%d" % [cx,cy]] = true
            if not bought.has("%d,%d" % [Gen.floor_div(cx,6),Gen.floor_div(cy,6)]):
                return {"code":403,"data":{"error":"parcel_not_owned"}}
            if Gen.terrain(Gen.SEED,cx,cy) == "water":
                return {"code":409,"data":{"error":"water_requires_bridge"}}
        for cell in cells:
            var x := int(cell[0])
            var y := int(cell[1])
            for adjacent in [Vector2i(x-1,y),Vector2i(x+1,y),Vector2i(x,y-1),Vector2i(x,y+1)]:
                if _has_road(adjacent.x,adjacent.y) and not requested.has("%d,%d" % [adjacent.x,adjacent.y]):
                    connection = true
        if not connection:
            return {"code":409,"data":{"error":"no_road_connection"}}
        var added := 0
        var changed := {}
        for cell in cells:
            var x := int(cell[0])
            var y := int(cell[1])
            var key := "%d,%d" % [x,y]
            if road_cells.has(key):
                continue
            road_cells[key]=true
            added+=1
            changed["%d,%d" % [Gen.floor_div(x,12),Gen.floor_div(y,12)]]=true
        for chunk in changed:
            versions[chunk]=int(versions.get(chunk,0))+1
        road_posts.append(data.duplicate(true))
        return {"code":200,"data":{"created":added}}
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
            r.append(_has_road(x,y))
        terrain.append(t)
        zones.append(z)
        roads.append(r)
    return {"cx":cx,"cy":cy,"terrain":terrain,"zones":zones,"roads":roads,"version":version,"etag":etag}

func _has_road(x: int, y: int) -> bool:
    return x==0 or y==0 or road_cells.has("%d,%d" % [x,y])
