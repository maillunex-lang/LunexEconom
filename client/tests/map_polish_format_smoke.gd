extends SceneTree
const Format = preload("res://i18n/format.gd")
const Words = preload("res://enterprises/strings.gd")
const Build = preload("res://screens/build.tscn")
func _initialize() -> void:
    call_deferred("_run")
func _run() -> void:
    assert(Format.money(400000.0)=="400 000 ₽")
    assert(Format.money(-150000)=="-150 000 ₽")
    assert(Format.number(123456789)=="123 456 789")
    assert(Format.days(1)=="1 игровой день")
    assert(Format.days(2)=="2 игровых дня")
    assert(Format.days(5)=="5 игровых дней")
    assert(Format.days(11)=="11 игровых дней")
    assert(Format.days(21)=="21 игровой день")
    assert(Format.days(24)=="24 игровых дня")
    var codes := [
        "invalid_zone","water","road_overlap","occupied","no_road_access","parcel_not_owned",
        "not_owner","outside_parcel","insufficient_funds","payment_failed","invalid_body",
        "invalid_coordinates","invalid_request_id","invalid_building","unknown_building",
        "unauthorized","forbidden","request_id_conflict","inventory_not_empty",
        "no_paid_construction","invalid_settings","invalid_name","invalid_running",
        "invalid_staffing","invalid_recipe","invalid_min_stock","not_found","warehouse_full",
        "invalid_inventory","invalid_road_cells","duplicate_road_cells",
        "roads_must_form_one_connected_path","road_crosses_city_boundary",
        "water_requires_bridge","road_overlaps_building","no_road_connection",
        "city_changed","parcel_unavailable","rate_limited"
    ]
    for code in codes:
        assert(Words.has_text("error.build."+code),"missing Russian error: "+code)
        assert(Words.error({"code":409,"data":{"error":code}})!=Words.get_text("error.build.unknown"),"unmapped: "+code)
    assert(Words.error({"code":409,"data":{"error":"no_road_access"}}).contains("дорог"))
    assert(Words.error({"code":409,"data":{"error":"invalid_zone"}}).contains("зон"))
    assert(Words.error({"code":409,"data":{"error":"future_code"}}).contains("future_code"))
    var page: Control = Build.instantiate()
    root.add_child(page)
    page.px=0
    page.py=0
    page.zone="free"
    page.wallet_balance=999999
    var field := {"id":"field","zones":["free"],"size":{"width":2,"height":2},"build_cost":150000}
    for cy in range(-1,7):
        for cx in range(-1,7):
            page.site_cells[page._key(cx,cy)]={"x":cx,"y":cy,"zone":"free","terrain":"ground","road":false,"occupied":false}
    assert(page._evaluate(field).get("reason","")=="road","missing-road placement check")
    page.site_cells[page._key(-1,0)]["road"]=true
    assert(bool(page._evaluate(field).get("allowed",false)),"road must unlock placement")
    page.wallet_balance=0
    assert(page._evaluate(field).get("reason","")=="money","missing initial-installment check")
    page.wallet_balance=999999
    for cell in page.site_cells.values():
        cell["zone"]="residential"
    assert(page._evaluate(field).get("reason","")=="zone","missing zone check")
    for cell in page.site_cells.values():
        cell["zone"]="free"
        cell["terrain"]="water"
        cell["road"]=false
    assert(page._evaluate(field).get("reason","")=="water","missing water check")
    print("map polish format smoke OK: integer rubles, 9 day variants, %d Russian error codes, placement reasons" % codes.size())
    page.queue_free()
    quit(0)
