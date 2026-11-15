extends SceneTree
## Deterministic swipe/pinch benchmark. Separates steady-state gestures from network loading.
const MapCanvas = preload("res://world/map_canvas.gd")
var canvas: Control
func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    root.size = Vector2i(1280, 720)
    canvas = MapCanvas.new()
    root.add_child(canvas)
    canvas.size = Vector2(1280, 720)
    var terrain: Array = []
    var zones: Array = []
    var roads: Array = []
    for y in range(12):
        var t: Array = []
        var z: Array = []
        var r: Array = []
        for x in range(12):
            t.append("ground" if x % 7 else "tree")
            z.append("residential" if x % 3 else "industrial")
            r.append(x == 0 or y == 0)
        terrain.append(t)
        zones.append(z)
        roads.append(r)
    for cy in range(-3, 4):
        for cx in range(-3, 4):
            canvas._on_chunk(Vector2i(cx, cy), {"terrain":terrain,"zones":zones,"roads":roads,"buildings":[],"version":0})
    for i in range(8):
        await process_frame
    var costs: Array[float] = []
    var swiping := InputEventMouseButton.new()
    swiping.button_index = MOUSE_BUTTON_LEFT
    swiping.pressed = true
    swiping.position = Vector2(350, 300)
    canvas._gui_input(swiping)
    for i in range(180):
        if i < 90:
            var mouse := InputEventMouseMotion.new()
            mouse.position = Vector2(350 + (i % 20) * 18, 300 + (i % 11) * 11)
            canvas._gui_input(mouse)
        elif i == 90:
            swiping.pressed = false
            swiping.position = Vector2(350, 300)
            canvas._gui_input(swiping)
        else:
            var wheel := InputEventMouseButton.new()
            wheel.pressed = true
            wheel.button_index = MOUSE_BUTTON_WHEEL_UP if (i / 12) % 2 == 0 else MOUSE_BUTTON_WHEEL_DOWN
            wheel.position = Vector2(480, 310)
            canvas._gui_input(wheel)
        var start := Time.get_ticks_usec()
        await process_frame
        costs.append(float(Time.get_ticks_usec() - start) / 1000.0)
    costs.sort()
    var total := 0.0
    for cost in costs:
        total += cost
    var average := total / costs.size()
    var worst: float = costs.back()
    var p95 := costs[int((costs.size() - 1) * 0.95)]
    print("GESTURE_FRAME_MS mean=%.3f p95=%.3f max=%.3f frames=%d" % [average,p95,worst,costs.size()])
    var baseline := float(OS.get_environment("LUNEX_FRAME_BASELINE_MAX_MS"))
    if baseline > 0.0:
        assert(worst <= baseline * 1.6 + 2.0, "gesture max frame regression against baseline")
    canvas.queue_free()
    quit(0)
