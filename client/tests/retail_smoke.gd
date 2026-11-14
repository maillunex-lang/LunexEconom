extends SceneTree
## Shop is in the build catalog, has a footprint, and a hidden catalog button does not take touches.

func _initialize() -> void:
    call_deferred("_run")

func _fail(message: String) -> void:
    push_error(message)
    print("RETAIL_SMOKE_FAIL " + message)
    quit(1)

func _run() -> void:
    var scene: PackedScene = load("res://world.tscn")
    if scene == null:
        _fail("world.tscn did not load")
        return
    var root: Node = scene.instantiate()
    get_root().add_child(root)
    await process_frame
    await process_frame
    var world = root.get_node_or_null("World")
    if world == null or world.build_size("shop") != Vector2i(2, 2):
        _fail("shop footprint")
        return
    var shop: Button = null
    var stack: Array[Node] = [root]
    while not stack.is_empty():
        var node: Node = stack.pop_back()
        if node is Button and str((node as Button).text).find("Магазин") >= 0:
            shop = node
        for child in node.get_children():
            stack.append(child)
    if shop == null:
        _fail("catalog has no shop button")
        return
    if not shop.is_visible_in_tree():
        var hit = root._hit_ui_button(shop.get_global_rect().get_center()) if root.has_method("_hit_ui_button") else null
        if hit == shop:
            _fail("hidden shop button took a touch")
            return
    print("RETAIL_SMOKE_PASS catalog/footprint/hidden-touch")
    root.queue_free()
    quit()
