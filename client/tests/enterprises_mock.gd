extends Node
var catalog: Dictionary = {
    "version":"test", "products":[], "recipes":[{"id":"field_grain","building":"field"}],
    "buildings":[{"id":"field","name":"Поле","description":"Зерно","category":"farm","zones":["free"],"size":{"width":2,"height":2},"build_cost":100,"build_days":3}]
}
var calls: Array = []
var ids: Array = []
var created: Dictionary = {}
var sold := false
func respond(path: String, method: int, payload: Dictionary, headers: PackedStringArray) -> Dictionary:
    calls.append({"path":path,"method":method,"payload":payload.duplicate(true),"headers":headers})
    if path == "/catalog":
        for header in headers:
            if header == 'If-None-Match: "test"':
                return {"code":304,"data":{}}
        return {"code":200,"etag":'"test"',"data":catalog}
    if path == "/enterprises" and method == HTTPClient.METHOD_POST:
        var key: String = str(payload.get("request_id",""))
        if not created.has(key):
            created[key] = ids.size()+1
            ids.append(created[key])
        return {"code":201,"data":{"id":created[key]}}
    if path == "/enterprises":
        return {"code":200,"data":{"enterprises":ids if not sold else []}}
    if path == "/enterprises/1":
        return {"code":200,"data":{"id":1,"name":"Поле","building_id":"field","stage":"operational","stage_index":4,"running":true,"staffing_bp":10000,"load_bp":7500,"wear":0,"recipe_id":"field_grain","inventory":{"grain":{"quantity":3,"quality":50}}}}
    if path == "/enterprises/1/report":
        return {"code":200,"data":{"reports":[{"month_index":1,"revenue":0,"expenses":10,"profit":-10}]}}
    if path == "/enterprises/1/settings":
        return {"code":200,"data":{"ok":true}}
    if path == "/enterprises/1/sell":
        sold = true
        return {"code":200,"data":{"price":50}}
    return {"code":404,"data":{"error":"not_found"}}
