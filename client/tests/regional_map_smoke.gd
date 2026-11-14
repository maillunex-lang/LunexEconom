extends SceneTree
## Offline geographic map integration: static payload, select, jump, visible UI.
func _initialize() -> void:
    call_deferred("_run")

func _fail(message: String) -> void:
    push_error("REGIONAL_MAP_SMOKE_FAIL " + message)
    quit(1)

func _run() -> void:
    var host = load("res://world.tscn").instantiate()
    get_root().add_child(host)
    await process_frame
    await process_frame
    if host.regional_map_panel == null:
        host.queue_free()
        _fail("missing panel")
        return
    var panel = host.regional_map_panel
    var cities: Array = []
    var regions: Array = []
    for i in 20:
        var city_id := "city_%d" % i
        if i == 0:
            city_id = "ufa"
        cities.append({
            "id": city_id, "name": ("Уфа" if i == 0 else "Город%d" % i),
            "region": "Регион %d" % i, "x": i * 20, "y": i * 9,
            "radius": 15, "population_estimate": 20000 + i * 1000,
            "streets": ["ул. Салавата Юлаева", "ул. Мира"],
            "specialization": "агро"
        })
        regions.append({"id": "region_%d" % i, "name": "Регион", "center_city_id": city_id})
    var route: Array = [{
        "from": "ufa", "to": "city_1", "cells": [[0, 0], [1, 0], [2, 0]]
    }]
    panel.set_geo_data(cities, regions, route)
    if not panel.loaded or panel.cities.size() != 20 or not panel.highway_cells.has(Vector2i(1,0)):
        host.queue_free()
        _fail("geo-data or highway cache incorrect")
        return
    panel.show()
    panel._place()
    await process_frame
    host.set_selection(Vector2i(2, 3))
    if not host.info.text.begins_with("Участок: Уфа"):
        host.queue_free()
        _fail("street name missing in plot label")
        return
    get_root().size = Vector2i(846, 388)
    await process_frame
    host._layout_ui_v1(Vector2(846, 388))
    panel._place()
    await process_frame
    if panel.get_global_rect().end.y > host.build_toolbar.get_global_rect().position.y + 2.0:
        host.queue_free()
        _fail("regional map overlaps navigation on narrow landscape")
        return
    if not panel.visible or panel.details == null or not panel.visit_button.visible:
        host.queue_free()
        _fail("panel not visible or no selected city")
        return
    panel.select_at(panel.project(cities[3]))
    if str(panel.current_city.get("id", "")) != "city_3":
        host.queue_free()
        _fail("touch selection not correct")
        return
    panel.map_zoom = 2.0
    panel.pan = Vector2(20, -5)
    panel.select_at(panel.project(cities[5]))
    if str(panel.current_city.get("id", "")) != "city_5":
        host.queue_free()
        _fail("selection did not follow zoom and pan")
        return
    panel._jump()
    if panel.visible or host.world.target_position != host.world.iso(100.0, 45.0):
        host.queue_free()
        _fail("camera transition failed")
        return
    panel.economy_view = {"cities": [{"id": "city_5", "population": 98, "jobs": 40, "wage": 900, "staffing": 1.0,
        "prices": {"honey": {"price": 480}}}], "lanes": [{"from": "city_5", "to": "ufa", "road_km": 175, "months": 2}],
        "shipments": [{"origin": "city_5", "destination": "ufa", "qty": 120}]}
    var econ := "\n".join(panel.economy_lines("city_5"))
    if econ.find("доставка 2 мес.") < 0 or econ.find("мёд 480") < 0 or econ.find("отправлено отсюда 120") < 0:
        host.queue_free()
        _fail("economy lines: " + econ)
        return
    host.queue_free()
    print("REGIONAL_MAP_SMOKE_PASS selection/touch/zoom/teleport/cache/economy")
    quit(0)
