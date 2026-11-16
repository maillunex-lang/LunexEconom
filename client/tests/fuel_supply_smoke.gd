extends SceneTree
const Supply = preload("res://screens/supply.tscn")
const WorldApi = preload("res://world/api.gd")
const Format = preload("res://i18n/format.gd")
const Words = preload("res://enterprises/strings.gd")

func _initialize() -> void:
    call_deferred("_run")

func _respond(path: String, method: int, _body: Dictionary, _headers: PackedStringArray) -> Dictionary:
    if path == "/enterprises/1":
        return {"code": 200, "data": {"id": 1, "city": "sterlitamak"}}
    if path == "/enterprises/1/supply" and method == HTTPClient.METHOD_GET:
        return {"code": 200, "data": {
            "inputs": [{"product_id": "grain", "name": "Зерно"}],
            "links": [{"product_id": "grain", "source_type": "enterprise",
                "source_enterprise_id": 4, "priority": 1, "share": 1000,
                "max_price": 1000, "min_quality": 0,
                "fuel_liters": 85, "fuel_cost": 5950, "transport_cost": 8500}],
            "fuel_failures": [{"product_id": "grain", "reason": "fuel_unaffordable"}]}}
    if path.begins_with("/market/"):
        return {"code": 200, "data": {"price": 25, "corridor_min": 10,
                                              "corridor_max": 40}}
    return {"code": 404, "data": {"error": "not_found"}}

func _run() -> void:
    var adapter := WorldApi.new()
    root.add_child(adapter)
    adapter.mock = Callable(self, "_respond")
    var screen := Supply.instantiate()
    root.add_child(screen)
    await screen.open(adapter, 1)
    for i in range(5):
        await process_frame
    assert(screen.row_controls.size() == 1)
    var panel: PanelContainer = screen.recipe_rows.get_child(1)
    var box: VBoxContainer = panel.get_child(0)
    var expected := "Топливо рейса: 85 л, " + Format.money(5950)
    var visible := false
    for child in box.get_children():
        if child is Label and expected in child.text:
            visible = true
    assert(visible, "Fuel line must be visible for intercity shipments")
    assert(Words.get_text("error.build.fuel_unaffordable") in screen.recipe_rows.get_child(0).text)
    assert("Не хватает топлива для рейса" == Words.get_text("error.build.fuel_missing"))
    assert(screen.trip_info({"fuel_liters": 0, "fuel_cost": 100}) == "")
    assert(screen.trip_info({"fuel_liters": 1, "fuel_cost": 70}).contains("1 л"))
    print("fuel supply smoke OK")
    quit(0)
