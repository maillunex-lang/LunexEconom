extends "res://tests/chain_mock.gd"
var unavailable := false
var forbidden := false
var conflict := false
var last_policy: Dictionary = {}
var last_supply: Dictionary = {}
var last_cells: Dictionary = {}
var policy_version := 4

func respond(path: String, method: int, data: Dictionary, headers: PackedStringArray) -> Dictionary:
    calls.append(path)
    if path == "/catalog":
        return {"code":200,"data":{"version":"ui-impl1","products":[
            {"id":"bread","name":"Хлеб","reference_price":100},
            {"id":"field_grain","name":"Зерно","reference_price":80}],
            "buildings":[{"id":"mill","name":"Мельница","role":"factory"},
                {"id":"grocery_store","name":"Магазин","role":"retail","allowed_goods":["bread"]}],
            "recipes":[]}}
    if path == "/enterprises/1":
        return {"code":200,"data":{"id":1,"name":"Мельница","building_id":"mill","city":"ufa",
            "stage_index":4,"inventory":{"bread":{"quantity":20,"quality":75}},"running":true}}
    if path == "/enterprises/1/report":
        return {"code":200,"data":{"reports":[]}}
    if path == "/enterprises/2":
        return {"code":200,"data":{"id":2,"name":"Магазин","building_id":"grocery_store","city":"ufa",
            "inventory":{"bread":{"quantity":8}}}}
    if path == "/enterprises/2/cells" and method == HTTPClient.METHOD_GET:
        return {"code":200,"data":{"capacity":1,"allowed_goods":["bread"],"cells":[
            {"cell_index":0,"product_id":"bread","price":110,"min_stock":5,"supply_link_slot":null,
             "min_price":60,"max_price":200}]}}
    if path == "/enterprises/2/cells" and method == HTTPClient.METHOD_PUT:
        last_cells = data
        return {"code":200,"data":{"cells":data.get("cells",[])}}
    if path.begins_with("/retail/ratings"):
        return {"code":200,"data":{"ratings":[
            {"enterprise_id":2,"cell_index":0,"rating":77,"price":110},
            {"enterprise_id":35,"cell_index":0,"rating":42,"price":105}]}}
    if path.begins_with("/enterprises/2/sales"):
        return {"code":200,"data":{"sales":[]}}
    if path.begins_with("/enterprises/1/sales-policy/bread"):
        if unavailable:
            return {"code":404,"data":{"error":"feature_disabled"}}
        if forbidden:
            return {"code":403,"data":{"error":"forbidden"}}
        if method == HTTPClient.METHOD_GET:
            return {"code":200,"data":{"active":{"mode":"public","price":100,"version":policy_version},
                "pending":null,"price_limits":{"min_price":50,"max_price":300}}}
        last_policy = data.duplicate(true)
        if conflict:
            return {"code":409,"data":{"error":"version_conflict","current_version":policy_version+1}}
        return {"code":200,"data":{"version":policy_version+1,"effective_day":9,"dry_run":data.get("dry_run",false)}}
    if path == "/enterprises/1/supply" and method == HTTPClient.METHOD_GET:
        return {"code":200,"data":{"inputs":{"field_grain":[]},"links":[]}}
    if path == "/enterprises/1/supply" and method == HTTPClient.METHOD_PUT:
        last_supply = data.duplicate(true)
        return {"code":200,"data":{"inputs":data.get("inputs",{})}}
    if path.begins_with("/supply/offers?"):
        if unavailable:
            return {"code":404,"data":{"error":"feature_disabled"}}
        return {"code":200,"data":{"offers":[
            {"seller_enterprise_id":22,"price":72,"quality":86,"reliability":94},
            {"seller_enterprise_id":24,"price":78,"quality":88,"reliability":91,"is_ai":true}]}}
    if path.begins_with("/market/"):
        return {"code":200,"data":{"price":75,"min_price":50,"max_price":120}}
    return {"code":404,"data":{"error":"not_found"}}
