extends SceneTree
var failures := 0
func _initialize() -> void:
    call_deferred("_run")
func _assert(ok: bool, message: String) -> void:
    if not ok:
        failures += 1
        print("FAIL ", message)
func _labels(node: Node, result: Array) -> void:
    if node is Label and node.is_visible_in_tree():
        result.append(node)
    for child in node.get_children():
        _labels(child, result)
func _run() -> void:
    for resolution in [Vector2i(846, 388), Vector2i(1280, 720), Vector2i(2340, 1080)]:
        root.content_scale_size = resolution
        root.size = resolution
        var hq = load("res://hq.tscn").instantiate()
        root.add_child(hq)
        hq._set_active(false)
        hq.sample_mode = true
        hq.apply_hq(load("res://hq/hq_api.gd").sample())
        await process_frame
        await process_frame
        var labels: Array = []
        _labels(hq, labels)
        for label in labels:
            var font: Font = label.get_theme_font("font")
            var font_size: int = label.get_theme_font_size("font_size")
            var min_width: float = font.get_string_size("ШШШ", HORIZONTAL_ALIGNMENT_LEFT, -1, font_size).x
            _assert(label.size.x >= min_width - 1.0, "%s label width %.1f < %.1f: %s" % [resolution, label.size.x, min_width, label.text.substr(0, 35)])
            _assert(label.size.y <= font.get_height(font_size) * 3.3 + 2, "%s label column height %.1f: %s" % [resolution, label.size.y, label.text.substr(0, 35)])
            _assert(font_size >= 14, "%s font smaller than 14: %s" % [resolution, label.text.substr(0, 35)])
        _assert(hq.header.get_global_rect().size.y <= maxf(49.0, resolution.y * 0.12), "%s header > 12%%" % resolution)
        var chart = hq.content.find_child("FinancialChart", true, false)
        _assert(chart != null and chart.is_visible_in_tree(), "%s missing chart" % resolution)
        _assert(hq.content.find_child("OverviewEnterprises", true, false) != null, "%s missing enterprise preview" % resolution)
        _assert(hq.content.find_child("OverviewPayments", true, false) != null, "%s missing payments" % resolution)
        var center: Rect2 = hq.body_scroll.get_global_rect()
        _assert(chart != null and chart.get_global_rect().end.y <= center.end.y + 2, "%s chart below fold" % resolution)
        var preview: Control = hq.content.find_child("OverviewEnterprises", true, false)
        _assert(preview != null and preview.get_global_rect().position.y < center.end.y, "%s enterprises below fold" % resolution)
        var cards: Array = hq.content.get_children()
        for i in range(cards.size() - 1):
            var a: Control = cards[i]
            var b: Control = cards[i + 1]
            _assert(a.get_global_rect().end.y <= b.get_global_rect().position.y + 1, "%s overlapping cards" % resolution)
        hq.queue_free()
        await process_frame
    print("HQ_VISUAL_SMOKE_PASS" if failures == 0 else "HQ_VISUAL_SMOKE_FAIL %d" % failures)
    quit(0 if failures == 0 else 1)
