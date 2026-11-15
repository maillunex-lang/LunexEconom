extends RefCounted
## The construction menu: field of activity -> (sub-field) -> building. One page per node, all built at once (hidden), switched by `show_page`.
## Kinds that the server knows but this tree does not list land under "Прочее", so a new building kind never disappears from the game.
## Data of a building (size, cost, product, inputs, deposit) comes from the host: server catalogue GET /catalog/goods when loaded, else the
## old constants. The zone and deposit rules are shown here and checked again by the server (docs/ZONING.md, docs/INDUSTRIES.md).
const TREE := [
	{"id": "agri", "title": "Сельское хозяйство", "hint": "пасеки и поля", "children": [{"kind": "farm"}, {"kind": "grain_field"}]},
	{"id": "extract", "title": "Добыча", "hint": "нефть, газ, песок, лес", "children": [
		{"kind": "mine"}, {"kind": "oil_well"}, {"kind": "gas_well"}, {"kind": "sand_pit"}, {"kind": "logging_camp"}]},
	{"id": "industry", "title": "Производство", "hint": "заводы и фабрики", "children": [
		{"id": "food", "title": "Пищевая промышленность", "hint": "мука и хлеб", "children": [{"kind": "mill"}, {"kind": "bread_plant"}]},
		{"id": "goods", "title": "Товары и промышленность", "hint": "заводы товаров", "children": [{"kind": "factory"}]}]},
	{"id": "trade", "title": "Торговля", "hint": "магазины", "children": [{"kind": "shop"}], "extra": "trade_catalog"},
	{"id": "storage", "title": "Склады и логистика", "hint": "хранение зерна и товаров", "children": [{"kind": "warehouse"}, {"kind": "elevator"}]},
]
const ZONE_TEXT := {
	"mill": "только в промзоне", "bread_plant": "только в промзоне", "factory": "только в промзоне",
	"grain_field": "промзона или свободная земля", "elevator": "промзона или свободная земля", "farm": "промзона или свободная земля",
	"mine": "промзона или свободная земля", "warehouse": "промзона или свободная земля",
	"oil_well": "на месторождении нефти", "gas_well": "на месторождении газа", "sand_pit": "на месторождении песка", "logging_camp": "в лесу (месторождение)",
	"shop": "в городе",
}
var host: Control
var content: VBoxContainer
var pages: Dictionary = {}
var current := "root"

func setup(new_host: Control, new_content: VBoxContainer) -> void:
	host = new_host
	content = new_content
	rebuild()

## Build (or rebuild after the catalogue arrived) every page.
func rebuild() -> void:
	for child in content.get_children():
		if child.name != "Header":
			child.queue_free()
	pages.clear()
	var listed: Dictionary = {}
	pages["root"] = _page_of(TREE, "", listed)
	var others: Array = []
	for kind in _known_kinds():
		if not listed.has(kind):
			others.append({"kind": kind})
	if not others.is_empty():
		var page: VBoxContainer = pages["root"]
		(page.get_child(0) as GridContainer).add_child(_sector_button({"id": "other", "title": "Прочее", "hint": "остальные здания"}, "other"))
		pages["other"] = _leaf_page(others, "root", "Прочее")
	for key in pages:
		content.add_child(pages[key])
	show_page(current if pages.has(current) else "root")

func _known_kinds() -> Array:
	var out: Array = []
	for kind in host.production.keys():
		if kind in ["school", "hospital", "park"]:
			continue                              # the city builds these from the budget, not the player
		out.append(str(kind))
	for kind in host.building_costs.keys():
		if kind in ["school", "hospital", "park"] or out.has(str(kind)):
			continue
		out.append(str(kind))
	return out

func _page_of(nodes: Array, parent: String, listed: Dictionary, title: String = "Строительство") -> VBoxContainer:
	var page := VBoxContainer.new()
	page.name = "Page_" + (parent if parent != "" else "root")
	page.add_theme_constant_override("separation", 8)
	if parent != "":
		page.add_child(_back_button(_parent_of(parent), title))
	var grid := GridContainer.new()
	grid.columns = 2
	grid.add_theme_constant_override("h_separation", 8)
	grid.add_theme_constant_override("v_separation", 8)
	page.add_child(grid)
	var leaves: Array = []
	for node in nodes:
		if node.has("kind"):
			leaves.append(node)
			listed[str(node["kind"])] = true
			continue
		var node_id: String = (parent + "/" if parent != "" else "") + str(node["id"])
		grid.add_child(_sector_button(node, node_id))
		pages[node_id] = _page_of(node["children"], node_id, listed, str(node["title"]))
		if node.get("extra", "") == "trade_catalog":
			(pages[node_id] as VBoxContainer).add_child(host._ui_button("Все отрасли торговли (33) · скоро", host._open_trade_catalog, 390))
	for leaf in leaves:
		page.add_child(_leaf_button(str(leaf["kind"])))
	return page

func _leaf_page(nodes: Array, parent: String, title: String) -> VBoxContainer:
	var page := VBoxContainer.new()
	page.name = "Page_other"
	page.add_theme_constant_override("separation", 8)
	page.add_child(_back_button(parent, title))
	for node in nodes:
		page.add_child(_leaf_button(str(node["kind"])))
	return page

func _parent_of(path: String) -> String:
	return path.get_base_dir() if path.contains("/") else "root"

func _back_button(target: String, title: String) -> Button:
	var b: Button = host._ui_button("‹ Назад   ·   " + title, func() -> void: show_page(target), 390)
	b.name = "Back"
	return b

func _sector_button(node: Dictionary, key: String) -> Button:
	var b: Button = host._ui_button("%s\n%s" % [str(node["title"]), str(node.get("hint", ""))], func() -> void: show_page(key), 190)
	b.name = "Sector_" + str(node["id"])
	b.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	return b

## "Name · 3×2 · 90 000 ₽" with the product and the rule of the place underneath.
func describe(kind: String) -> Dictionary:
	var size: Vector2i = host.world.build_size(kind)
	var cost := int(host.building_costs.get(kind, 0))
	var title := str(host.KIND_NAMES.get(kind, kind))
	if host.goods_recipes.has(kind):
		title = str(host.goods_recipes[kind].get("name", title))
	var lines := PackedStringArray()
	var p = host.production.get(kind, null)
	if p is Dictionary:
		var pid := str(p.get("product_id", ""))
		if pid != "":
			lines.append("выпуск: %s %d/мес" % [host._good_name(pid), int(p.get("output", 0))])
		var inputs = p.get("inputs", {})
		if inputs is Dictionary and not (inputs as Dictionary).is_empty():
			var parts := PackedStringArray()
			for raw in (inputs as Dictionary).keys():
				parts.append("%s %d" % [host._good_name(str(raw)), int(inputs[raw])])
			lines.append("сырьё: " + ", ".join(parts))
		if int(p.get("storage", 0)) > 0:
			lines.append("склад на %d" % int(p["storage"]))
	if ZONE_TEXT.has(kind):
		lines.append(str(ZONE_TEXT[kind]))
	return {"title": title, "size": size, "cost": cost, "details": " · ".join(lines)}

func _leaf_button(kind: String) -> Button:
	var d := describe(kind)
	var size: Vector2i = d["size"]
	var text := "%s · %d×%d · %s" % [d["title"], size.x, size.y, host._fmt_money_short(int(d["cost"]))]
	if str(d["details"]) != "":
		text += "\n" + str(d["details"])
	var b: Button = host._ui_button(text, func() -> void: host._choose_ui_build(kind), 390)
	b.name = "Kind_" + kind
	b.custom_minimum_size = Vector2(390, 66)
	b.alignment = HORIZONTAL_ALIGNMENT_LEFT
	return b

func show_page(path: String) -> void:
	current = path if pages.has(path) else "root"
	for key in pages:
		(pages[key] as Control).visible = key == current
	if is_instance_valid(host) and host.catalog_panel != null:
		host.catalog_panel.reset_size()            # the panel shrinks to the page: a short page must not keep the height of a long one
	if is_instance_valid(host) and host.has_method("_layout_ui_v1"):
		host.call_deferred("_layout_ui_v1")
