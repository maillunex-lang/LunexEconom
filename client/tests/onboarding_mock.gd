extends "res://tests/world_mock.gd"
## Owner-authenticated onboarding fixtures layered over the world mock.
var plan_mode := "ok"
var plan_calls := 0
var fail_purchase := false
var mock_account := "777"
var has_field := false
var has_land := false
var mock_day := 0

func respond(path: String, method: int, data: Dictionary, headers: PackedStringArray) -> Dictionary:
    if path.begins_with("/enterprises/plan?"):
        plan_calls += 1
        calls.append(path)
        await get_tree().process_frame
        if plan_mode == "far":
            return {"code":200,"data":{"ok":false,"reason":"road_unreachable","road_cells":[],"road_cost":0}}
        return {"code":200,"data":{
            "ok":true,"reason":null,"road_cells":[[14,3],[15,3]],"road_cost":2000,
            "initial_payment":45000,"total_initial":47000,
            "can_afford":plan_mode != "money","shortfall":7000 if plan_mode == "money" else 0}}
    if fail_purchase and path == "/enterprises" and method == HTTPClient.METHOD_POST:
        return {"code":409,"data":{
            "error":"insufficient_funds","road_cost":2000,"required":47000,"shortfall":7000}}
    if path == "/auth/me":
        return {"code":200,"data":{"id":int(mock_account),"username":"test-company"}}
    if path == "/clock":
        return {"code":200,"data":{"day_index":mock_day,"month":1,"day":mock_day+1,"year":2027}}
    if path == "/enterprises" and method == HTTPClient.METHOD_GET:
        return {"code":200,"data":{"enterprises":[1] if has_field else []}}
    if path == "/enterprises/1":
        return {"code":200,"data":{"id":1,"building_id":"field","stage_index":4,"stage":"operational",
            "inventory":{"grain":{"quantity":0,"quality":50}}}}
    if path.begins_with("/land/parcels?") and has_land:
        return {"code":200,"data":{"parcels":[{"px":0,"py":0,
            "owner_kind":"player","owner_ref":mock_account}]}}
    return await super.respond(path, method, data, headers)
