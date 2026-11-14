extends PanelContainer
## Read-only lightweight frame diagnostics. Toggle from Menu; no permanent _draw.
var host: Control
var output: Label
var timer: Timer

func setup(parent: Control) -> void:
    host = parent
    name = "PerfOverlay"
    add_theme_stylebox_override("panel", host._style())
    mouse_filter = Control.MOUSE_FILTER_IGNORE
    host.get_node("UIOverlay").add_child(self)
    output = Label.new()
    output.add_theme_font_size_override("font_size", 13)
    add_child(output)
    timer = Timer.new()
    timer.wait_time = 0.5
    timer.timeout.connect(refresh)
    add_child(timer)
    timer.start()
    hide()
    host.get_viewport().size_changed.connect(_place)

func _place() -> void:
    if host == null:
        return
    var viewport := host.get_viewport_rect().size
    size = Vector2(minf(370.0, viewport.x * 0.40), 83)
    position = Vector2(maxf(8, viewport.x - size.x - 26), 76)

func refresh() -> void:
    if not visible or host == null:
        return
    var active: Dictionary = host.world.active_chunks
    var drawing := 0.0
    for chunk in active.values():
        drawing += float(chunk.last_draw_usec) / 1000.0
    var city_count := 0
    if host.regional_map_panel != null and host.world.camera != null:
        var camera: Camera2D = host.world.camera
        var visible_half: Vector2 = host.world.get_viewport_rect().size * 0.5 / camera.zoom
        for city in host.regional_map_panel.cities:
            if city is Dictionary:
                var scene_point: Vector2 = host.world.iso(float(city.get("x", 0)), float(city.get("y", 0)))
                var delta: Vector2 = scene_point - camera.position
                if absf(delta.x) <= visible_half.x and absf(delta.y) <= visible_half.y:
                    city_count += 1
    var fps := Engine.get_frames_per_second()
    var frame_ms := Performance.get_monitor(Performance.TIME_PROCESS) * 1000.0
    output.text = "FPS %d · кадр %.1f мс\nЧанки %d · города рядом %d\nОбновление чанков %.1f мс*" % [fps, frame_ms, active.size(), city_count, drawing]

func toggle() -> void:
    visible = not visible
    if visible:
        _place()
        refresh()
