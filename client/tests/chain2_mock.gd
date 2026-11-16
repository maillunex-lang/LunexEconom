extends "res://tests/world_mock.gd"
## Server-shaped synthetic full catalog, no embedded production definitions.
var material_mode := "short"
var store_id := "fuel_station"
var all_products: Array = []
var all_buildings: Array = []
var all_recipes: Array = []
var store_cells: Array = []

func _ready() -> void:
    super._ready()
    for i in range(41):
        var id := "item_%02d" % i
        all_products.append({"id":id,"name":"Товар %d" % i,"unit":"kg" if i == 0 else "piece","reference_price":100+i})
    all_products[0]["id"] = "cement"
    all_products[0]["name"] = "Цемент"
    all_products[1]["id"] = "fuel"
    all_products[1]["name"] = "Топливо"
    for i in range(42):
        var id := "factory_%02d" % i
        if i == 0: id = "fuel_station"
        if i == 1: id = "hardware_store"
        var category := "factory"
        if i < 2: category = "retail"
        if i == 2: category = "unknown_future_category"
        all_buildings.append({"id":id,"name":"Здание %d" % i,"description":"","category":category,
            "role":"retail" if i < 2 else "factory","size":{"width":2,"height":2},"zones":["free","industrial"],
            "build_cost":200+i,"build_days":2,"allowed_goods":["fuel"] if i == 0 else (["cement"] if i == 1 else [])})
    for i in range(41):
        all_recipes.append({"id":"recipe_%d" % i,"building":"factory_%02d" % (i+1)})

func respond(path: String, method: int, payload: Dictionary, headers: PackedStringArray) -> Dictionary:
    if path == "/catalog":
        return {"code":200,"etag":"chain2-41-42","data":{"version":"chain2-41-42","products":all_products,"buildings":all_buildings,"recipes":all_recipes}}
    if path == "/enterprises/1":
        var data := {"id":1,"building_id":"factory_02","stage_index":0,"stage":"foundation","running":false,
          "inventory":{},"staffing_bp":0,"load_bp":0,"wear":0}
        if material_mode != "off":
            data["materials_required"] = {"stage":"foundation", "items":[{"product_id":"cement","needed":80,"have":40 if material_mode in ["short", "short_ids"] else 80}],
                "short":["cement"] if material_mode == "short_ids" else ([{"product_id":"cement","missing":40}] if material_mode == "short" else [])}
        return {"code":200,"data":data}
    if path == "/enterprises/1/report":
        return {"code":200,"data":{"reports":[]}}
    if path == "/enterprises/2":
        return {"code":200,"data":{"id":2,"name":"Серверное имя","building_id":store_id,"city":"ufa","stage_index":4,"running":true,"inventory":{}}}
    if path == "/enterprises/2/report":
        return {"code":200,"data":{"reports":[]}}
    if path == "/enterprises/2/cells" and method == HTTPClient.METHOD_GET:
        return {"code":200,"data":{"capacity":1,"allowed_goods":["fuel","cement"],"cells":store_cells}}
    if path == "/enterprises/2/cells" and method == HTTPClient.METHOD_PUT:
        store_cells = payload.get("cells", [])
        return {"code":200,"data":{"cells":store_cells}}
    if path.begins_with("/retail/ratings"):
        return {"code":200,"data":{"items":[]}}
    if path.begins_with("/enterprises/2/sales"):
        return {"code":200,"data":{"sales":[]}}
    if path == "/enterprises":
        return {"code":200,"data":{"enterprises":[1,2]}}
    return await super.respond(path,method,payload,headers)
