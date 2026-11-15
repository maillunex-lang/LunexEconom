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
    var drawing := float(host.world.last_build_usec) / 1000.0
    var city_count := 0
    if host.regional_map_panel != null and host.world.camera != null:
        var reach: float = host.world.camera.size / host.world.CELL       # cells from the screen centre to its edge, roughly
        var here: Vector2i = host.world.cell_of(host.world.focus)
        for city in host.regional_map_panel.cities:
            if city is Dictionary:
                if absf(float(int(city.get("x", 0)) - here.x)) <= reach and absf(float(int(city.get("y", 0)) - here.y)) <= reach:
                    city_count += 1
    var fps := Engine.get_frames_per_second()
    var frame_ms := Performance.get_monitor(Performance.TIME_PROCESS) * 1000.0
    output.text = "FPS %d · кадр %.1f мс\nЧанки %d · города рядом %d\nОбновление чанков %.1f мс*" % [fps, frame_ms, active.size(), city_count, drawing]

func toggle() -> void:
    visible = not visible
    if visible:
        _place()
        refresh()
