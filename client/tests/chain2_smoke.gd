extends SceneTree
const Mock = preload("res://tests/chain2_mock.gd")
const WorldApi = preload("res://world/api.gd")
const Catalog = preload("res://enterprises/catalog.gd")
const Enterprises = preload("res://screens/enterprises.tscn")
const Build = preload("res://screens/build.tscn")
const Store = preload("res://screens/store.tscn")

func _initialize() -> void:
    call_deferred("_run")

func _has_text(node: Node, fragment: String) -> bool:
    if (node is Label or node is Button) and fragment in node.text:
        return true
    for child in node.get_children():
        if _has_text(child, fragment):
            return true
    return false

func _count_labels(node: Node, fragment: String) -> int:
    var count := 0
    if (node is Label or node is Button) and fragment in node.text:
        count += 1
    for child in node.get_children():
        count += _count_labels(child, fragment)
    return count

func _run() -> void:
    var mock := Mock.new()
    root.add_child(mock)
    var adapter := WorldApi.new()
    root.add_child(adapter)
    adapter.mock = Callable(mock, "respond")
    var catalog := Catalog.new()
    root.add_child(catalog)
    catalog.configure(adapter)
    assert(await catalog.update())
    assert(catalog.data.products.size() == 41)
    assert(catalog.buildings().size() == 42)
    assert(catalog.data.recipes.size() == 41)
    for item in catalog.data.products:
        assert(not catalog.product_name(str(item.id)).is_empty())
    for item in catalog.buildings():
        assert(not catalog.building_name(str(item.id)).is_empty())
    assert(catalog.product_unit("cement") == "кг")
    assert(catalog.product_unit("unknown") == "ед.")
    var enterprises := Enterprises.instantiate()
    root.add_child(enterprises)
    enterprises.service.configure(adapter)
    enterprises.catalog.configure(adapter)
    await enterprises.show_detail(1)
    await process_frame
    assert(_has_text(enterprises.body,"Цемент: нужно 80 кг, на складе 40 кг"))
    assert(_has_text(enterprises.body,"Стройка ждёт материалы"))
    assert(_has_text(enterprises.body,"Не хватает материала: Цемент"))
    mock.material_mode = "short_ids"
    await enterprises.show_detail(1)
    await process_frame
    assert(_has_text(enterprises.body,"Стройка ждёт материалы"))
    mock.material_mode = "ok"
    await enterprises.show_detail(1)
    await process_frame
    assert(_has_text(enterprises.body,"Цемент: нужно 80 кг, на складе 80 кг"))
    assert(not _has_text(enterprises.body,"Стройка ждёт материалы"))
    mock.material_mode = "off"
    await enterprises.show_detail(1)
    await process_frame
    assert(not _has_text(enterprises.body,"Материалы для стадии"))
    var build := Build.instantiate()
    root.add_child(build)
    build.catalog.configure(adapter)
    build.service.configure(adapter)
    build.zone = "free"
    build.wallet_balance = 100000
    await build._load()
    assert(build.catalog.buildings().size() == 42)
    assert(build.category.item_count >= 4)
    assert(build.category.get_item_text(build.category.item_count-1) == "Прочее")
    assert(build.rows.get_child_count() == 42)
    build.category.select(build.category.item_count - 1)
    build._render()
    await process_frame
    assert(build.rows.get_child_count() == 1)
    build.category.select(0)
    build._render()
    await process_frame
    assert(build.rows.get_child_count() == 42)
    var store := Store.instantiate()
    root.add_child(store)
    await store.open(adapter,2)
    assert(store.row_controls.size() == 1)
    var option: OptionButton = store.row_controls[0].product
    assert(option.item_count == 1)
    assert(option.get_item_text(0) == "Топливо")
    assert(int(store.row_controls[0].price.value) == 101)
    assert(_has_text(store.rows,"Эталон: 101 ₽"))
    await enterprises.show_detail(2)
    await process_frame
    assert(_has_text(enterprises.body,"Здание 0"))
    assert(_has_text(enterprises.body,"Магазин"))
    print("chain2 smoke OK: 41 products, 42 buildings, materials on/off, retail fuel station")
    quit(0)
