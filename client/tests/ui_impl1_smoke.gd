extends SceneTree
const Mock = preload("res://tests/ui_impl1_mock.gd")
const Adapter = preload("res://world/api.gd")
const Sales = preload("res://screens/sales_policy.tscn")
const Enterprises = preload("res://screens/enterprises.tscn")
const Supply = preload("res://screens/supply.tscn")
const Store = preload("res://screens/store.tscn")
const SIZES := [Vector2i(1920,1080),Vector2i(2400,1080)]

func _initialize() -> void:
    call_deferred("_run")

func _has_text(node: Node, sample: String) -> bool:
    if node is Label or node is Button:
        if sample in node.text:
            return true
    for child in node.get_children():
        if _has_text(child,sample):
            return true
    return false

func _run() -> void:
    var mock := Mock.new()
    root.add_child(mock)
    var adapter := Adapter.new()
    root.add_child(adapter)
    adapter.mock = Callable(mock,"respond")
    var sales := Sales.instantiate()
    root.add_child(sales)
    for index in range(sales.mode.item_count):
        assert(sales.mode.get_item_metadata(index) in ["private","public","mixed","invited"])
    await sales.open(adapter,1,"bread")
    assert(not sales.apply_button.disabled)
    assert(sales.version == 4)
    assert(int(sales.price.min_value) == 50 and int(sales.price.max_value) == 300)
    sales.mode.select(2)
    sales._update_fields()
    sales.reserve.value = 35
    await sales._submit(true)
    assert(mock.last_policy.get("dry_run") == true)
    assert(mock.last_policy.get("reserve_bp") == 3500)
    var dry_request := str(mock.last_policy.get("request_id", ""))
    await sales._submit(false)
    assert(mock.last_policy.get("request_id") == dry_request)
    assert(not mock.last_policy.get("dry_run"))
    assert(mock.last_policy.get("expected_version") == 4)
    sales.mode.select(3)
    sales._update_fields()
    sales.invites.text = "7, 12"
    await sales._submit(true)
    assert(mock.last_policy.get("invited_owner_ids") == [7,12])
    mock.conflict = true
    await sales._submit(false)
    assert(_has_text(sales,"Данные изменились"))
    mock.conflict = false
    mock.unavailable = true
    await sales.open(adapter,1,"bread")
    assert(sales.apply_button.disabled)
    assert(_has_text(sales,"скоро будет доступна"))
    mock.unavailable = false
    mock.forbidden = true
    await sales.open(adapter,1,"bread")
    assert(_has_text(sales,"Нет прав"))
    mock.forbidden = false
    var enterprises := Enterprises.instantiate()
    root.add_child(enterprises)
    enterprises.service.configure(adapter)
    enterprises.catalog.configure(adapter)
    assert(await enterprises.catalog.update())
    await enterprises.show_detail(1)
    assert(not enterprises.detail_mode)
    assert(_has_text(enterprises.body,"Склад готовой продукции"))
    assert(_has_text(enterprises.body,"Куда продавать"))
    enterprises.detail_mode = true
    await enterprises.show_detail(1)
    assert(_has_text(enterprises.body,"Кратко"))
    var supply := Supply.instantiate()
    root.add_child(supply)
    await supply.open(adapter,1)
    assert(supply.row_controls.size() == 1)
    assert(supply._offers_area.get_child_count() >= 2)
    supply._choose_offer({"seller_enterprise_id":22,"price":72},"field_grain")
    assert(supply.selected_links.size() == 1)
    assert(int(supply.selected_links[0].share) == 1000)
    supply._choose_offer({"seller_enterprise_id":24,"price":78},"field_grain")
    assert(supply.selected_links.size() == 2)
    assert(int(supply.selected_links[0].share) == 500 and int(supply.selected_links[1].share) == 500)
    supply._choose_offer({"seller_enterprise_id":26,"price":80},"field_grain")
    assert(supply.selected_links.size() == 3)
    assert(int(supply.selected_links[0].share) + int(supply.selected_links[1].share) + int(supply.selected_links[2].share) == 1000)
    supply._choose_offer({"seller_enterprise_id":28,"price":90},"field_grain")
    assert(supply.selected_links.size() == 3)
    await supply._save()
    assert(mock.last_supply.has("inputs"))
    assert(mock.last_supply.inputs.has("field_grain"))
    assert(mock.last_supply.inputs.field_grain.size() == 3)
    assert(int(mock.last_supply.inputs.field_grain[0].source_enterprise_id) == 22)
    mock.unavailable = true
    await supply._load_offers("field_grain")
    assert(_has_text(supply._offers_area,"пока недоступны"))
    mock.unavailable = false
    var store := Store.instantiate()
    root.add_child(store)
    await store.open(adapter,2)
    assert(store.row_controls.size() == 1)
    assert(int(store.row_controls[0].price.max_value) == 200)
    assert(_has_text(store.rows,"Рейтинг: 77"))
    assert(_has_text(store.rows,"Остаток: 8"))
    assert(not _has_text(store,"конкурент"))
    store.row_controls[0].price.value = 120
    await store._save()
    assert(int(mock.last_cells.cells[0].price) == 120)
    for bounds in SIZES:
        root.size = bounds
        sales.resize_ui(bounds)
        store.resize_ui(bounds)
        supply.resize_ui(bounds)
        assert(sales.layout._wide and store._columns._wide and supply._columns._wide)
        for item in [sales, supply, store, enterprises]:
            item.hide()
        for entry in [[sales,"sales"],[supply,"suppliers"],[store,"store"],[enterprises,"factory"]]:
            entry[0].show()
            await process_frame
            await process_frame
            _capture("ui_impl1_" + str(entry[1]),bounds)
            entry[0].hide()
    print("ui impl1 smoke OK: modes, dry run, version conflict, disabled, forbidden, suppliers, ratings, cells, wide layout")
    quit(0)

func _capture(name: String, bounds: Vector2i) -> void:
    var directory := OS.get_environment("LUNEX_SCREENSHOT_DIR")
    if directory.is_empty():
        return
    DirAccess.make_dir_recursive_absolute(directory)
    assert(root.get_viewport().get_texture().get_image().save_png(directory.path_join("%s_%dx%d.png" % [name,bounds.x,bounds.y])) == OK)
