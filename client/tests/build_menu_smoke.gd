extends SceneTree
## The construction menu: field of activity -> sub-field -> building, costs and products from the server catalogue, the zone and deposit
## rules in the preview, back navigation, and that choosing a building starts placement. Always quits.
var failures := 0

func _initialize() -> void:
	call_deferred("_run")

func _check(condition: bool, label: String) -> void:
	if not condition:
		failures += 1
		print("FAIL: ", label)

func _find(node: Node, name: String) -> Node:
	if node.name == name:
		return node
	for child in node.get_children():
		var found := _find(child, name)
		if found != null:
			return found
	return null

func _run() -> void:
	var host: Control = load("res://world.tscn").instantiate()
	get_root().add_child(host)
	await process_frame
	await process_frame
	var sample: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://tests/goods_catalog_sample.json"))
	host.apply_goods_catalog(sample)
	await process_frame
	var menu = host.build_menu
	_check(menu != null, "the menu exists")
	for sector in ["agri", "extract", "industry", "trade", "storage"]:
		_check(_find(menu.content, "Sector_" + sector) != null, "sector " + sector)
	_check(menu.pages.has("industry/food") and menu.pages.has("industry/goods"), "sub-fields under Production")
	# only the root page is visible at start
	menu.show_page("root")
	_check(menu.pages["root"].visible and not menu.pages["agri"].visible, "root page only")
	# all kinds are reachable and priced from the catalogue
	for kind in ["farm", "grain_field", "flax_camp", "mine", "oil_well", "gas_well", "sand_pit", "logging_camp", "stone_pit", "iron_mine", "coal_mine", "mill", "bread_plant", "cement_plant", "brick_yard", "sawmill", "steel_plant", "metalworks", "machine_plant", "textile_mill", "garment_plant", "refinery", "electronics_plant", "factory", "shop", "warehouse", "elevator"]:
		var button := _find(menu.content, "Kind_" + kind) as Button
		_check(button != null, "a button for " + kind)
		if button != null:
			_check(button.text.contains("×"), "size shown for " + kind + ": " + button.text)
	var mill := _find(menu.content, "Kind_mill") as Button
	_check(mill != null and mill.text.contains("Мельница") and mill.text.contains("только в промзоне") and mill.text.contains("Зерно") or (mill != null and mill.text.contains("зерно")), "the mill shows its product, input and place: " + (mill.text if mill != null else ""))
	var well := _find(menu.content, "Kind_oil_well") as Button
	_check(well != null and well.text.contains("месторождении"), "a well mentions its deposit")
	_check(int(host.building_costs.get("mill", 0)) == 180000, "the mill price comes from the catalogue")
	_check(not menu.pages.has("other"), "no kind is left in Other")
	_check(host.world.build_size("steel_plant") != Vector2i.ZERO, "a catalogue-only kind has a footprint")
	# navigation: Production -> Food -> back -> back
	menu.show_page("industry")
	_check(menu.pages["industry"].visible and not menu.pages["root"].visible, "opened a sector")
	menu.show_page("industry/food")
	_check(menu.pages["industry/food"].visible, "opened a sub-field")
	var back := _find(menu.pages["industry/food"], "Back") as Button
	back.pressed.emit()
	_check(menu.current == "industry", "back goes one level up: " + menu.current)
	(_find(menu.pages["industry"], "Back") as Button).pressed.emit()
	_check(menu.current == "root", "back to the root")
	# choosing a building starts placement and closes the menu
	menu.show_page("industry/food")
	(_find(menu.content, "Kind_bread_plant") as Button).pressed.emit()
	_check(host.world.build_type == "bread_plant", "a building was chosen: " + host.world.build_type)
	_check(not host.catalog_panel.visible, "the menu closed")
	host.world.cancel_build()
	# deposit rule: a well needs its deposit, a mill needs the industrial zone
	var world = host.world
	world.set_zones({"enabled": true, "cities": [{"id": "ufa", "x": 0, "y": 0, "radius": 63, "wedge_angle": 90}]})
	var cells := [Vector2i(30, 30), Vector2i(31, 30), Vector2i(30, 31), Vector2i(31, 31)]
	_check(world.build_refusal("oil_well", cells).contains("месторождение"), "no deposit: " + world.build_refusal("oil_well", cells))
	world.set_deposits([{"id": "dep:ufa:oil:0", "resource": "oil", "region": "ufa", "x": 30, "y": 30, "width": 2, "height": 2, "initial": 2400, "remaining": 2400}])
	_check(world.build_refusal("oil_well", cells) == "", "on the deposit the well is allowed")
	_check(world.build_refusal("gas_well", cells).contains("газа"), "a gas well on an oil deposit is refused")
	_check(world.build_refusal("mill", [Vector2i(1, 1), Vector2i(2, 1), Vector2i(3, 1), Vector2i(1, 2), Vector2i(2, 2), Vector2i(3, 2)]).contains("центр"), "a mill in the centre")
	world.flush_all()
	_check(world.active_chunks.size() > 0, "chunks rebuilt with the deposit tint")
	host.queue_free()
	await process_frame
	if failures == 0:
		print("BUILD_MENU_SMOKE_PASS sectors/pages/catalogue/back/choose/deposit/zone")
		quit(0)
	else:
		print("BUILD_MENU_SMOKE_FAIL ", failures)
		quit(1)
