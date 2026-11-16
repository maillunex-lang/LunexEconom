extends Node
var calls: Array[String] = []
var supply_links: Array = []
var cells: Array = []

func respond(path: String, method: int, data: Dictionary, _headers: PackedStringArray) -> Dictionary:
    calls.append(path)
    if path == "/enterprises/1":
        return {"code":200,"data":{"id":1,"name":"Мельница","building_id":"mill","city":"ufa","role":"production","running":true}}
    if path == "/enterprises/2":
        return {"code":200,"data":{"id":2,"name":"Магазин","building_id":"grocery_store","city":"ufa","role":"retail","running":true}}
    if path == "/enterprises/1/supply" and method == HTTPClient.METHOD_GET:
        return {"code":200,"data":{"inputs":[{"product_id":"field_grain","name":"Зерно"}],"links":supply_links}}
    if path == "/enterprises/1/supply" and method == HTTPClient.METHOD_PUT:
        supply_links = data.get("links",[])
        return {"code":200,"data":{"links":supply_links}}
    if path.begins_with("/market/"):
        return {"code":200,"data":{"price":90,"corridor_min":70,"corridor_max":120}}
    if path == "/enterprises/2/cells" and method == HTTPClient.METHOD_GET:
        return {"code":200,"data":{"capacity":4,"allowed_goods":[{"id":"bread","name":"Хлеб"}],"cells":cells}}
    if path == "/enterprises/2/cells" and method == HTTPClient.METHOD_PUT:
        cells = data.get("cells",[])
        return {"code":200,"data":{"cells":cells}}
    if path.begins_with("/retail/ratings"):
        return {"code":200,"data":{"items":[{"price":90,"rating":70},{"price":100,"rating":60}]}}
    if path.begins_with("/enterprises/2/sales"):
        return {"code":200,"data":{"sales":[{"quantity":12,"price":90,"revenue":1080}]}}
    return {"code":404,"data":{"error":"not_found"}}
