extends RefCounted
## Exact virtual road skeleton from server/world/core.py, without server-only edits.
const Gen = preload("res://world/generator.gd")

static func trunk_edges(cities: Array) -> Array:
    var by_id := {}
    var remaining: Array[String] = []
    for city in cities:
        var id: String = str(city["id"])
        by_id[id] = city
        if id != "ufa":
            remaining.append(id)
    assert(by_id.has("ufa"))
    var selected: Array[String] = ["ufa"]
    var edges: Array = []
    while not remaining.is_empty():
        var best_distance := 9223372036854775807
        var best_a := ""
        var best_b := ""
        for a in selected:
            for b in remaining:
                var ac: Dictionary = by_id[a]
                var bc: Dictionary = by_id[b]
                var length := absi(int(ac["x"])-int(bc["x"])) + absi(int(ac["y"])-int(bc["y"]))
                if length < best_distance or (length == best_distance and (best_a.is_empty() or a < best_a or (a == best_a and b < best_b))):
                    best_distance = length
                    best_a = a
                    best_b = b
        edges.append([best_a,best_b,best_distance])
        selected.append(best_b)
        remaining.erase(best_b)
    return edges

static func _path_contains(ax: int, ay: int, bx: int, by: int, x: int, y: int) -> bool:
    return (y==ay and x>=mini(ax,bx) and x<=maxi(ax,bx)) or (x==bx and y>=mini(ay,by) and y<=maxi(ay,by))

static func virtual_road(x: int, y: int, cities: Array, edges: Array = []) -> bool:
    var by_id := {}
    for city in cities:
        by_id[str(city["id"])] = city
    var roads: Array = edges if not edges.is_empty() else trunk_edges(cities)
    for edge in roads:
        var a: Dictionary = by_id[str(edge[0])]
        var b: Dictionary = by_id[str(edge[1])]
        if _path_contains(int(a["x"]),int(a["y"]),int(b["x"]),int(b["y"]),x,y):
            return true
    for city in cities:
        var dx := x - int(city["x"])
        var dy := y - int(city["y"])
        var distance := maxi(absi(dx),absi(dy))
        var level := int(city.get("level",1))
        var base := int(city.get("base_radius",12))
        if distance > Gen.radius_at_level(base,level):
            continue
        if dx==0 or dy==0:
            return true
        for ring in range(1,level+1):
            if distance == Gen.radius_at_level(base,ring):
                return true
    return false

static func authoritative_zone(x: int, y: int, cities: Array) -> String:
    var winner: Dictionary = {}
    var best_distance := 9223372036854775807
    for city in cities:
        var dx := x - int(city["x"])
        var dy := y - int(city["y"])
        var distance := maxi(absi(dx),absi(dy))
        if distance > Gen.radius_at_level(int(city.get("base_radius",12)),int(city.get("level",1))):
            continue
        var id: String = str(city.get("id",""))
        if distance < best_distance or (distance == best_distance and (winner.is_empty() or id < str(winner.get("id","")))):
            best_distance = distance
            winner = city
    if winner.is_empty():
        return "free"
    return Gen.zone(x,y,int(winner["x"]),int(winner["y"]),int(winner.get("base_radius",12)),int(winner.get("level",1)))
