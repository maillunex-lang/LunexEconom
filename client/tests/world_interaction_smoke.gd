extends SceneTree
const API = preload("res://world/api.gd")
const Mock = preload("res://tests/world_mock.gd")
const Map = preload("res://screens/map.tscn")
var page: Control
var mock: Node
var purchased := 0

func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    root.size = Vector2i(1280,720)
    mock = Mock.new()
    root.add_child(mock)
    page = Map.instantiate()
    root.add_child(page)
    page.api.mock = Callable(mock,"respond")
    page.wallet_changed.connect(func(): purchased+=1)
    page.open("https://test.invalid","dummy")
    for i in range(70):
        await process_frame
        if page.canvas.tiles.size() >= 9 and page.stream.parcels.size()>=9:
            break
    assert(page.options.item_count==20,"city selection")
    assert(page.canvas.tiles.size()>=9,"map chunks")
    var canvas: Control = page.canvas
    var start: Vector2 = canvas.center
    var mouse := InputEventMouseButton.new()
    mouse.button_index = MOUSE_BUTTON_LEFT
    mouse.pressed = true
    mouse.position = Vector2(400,300)
    canvas._gui_input(mouse)
    var motion := InputEventMouseMotion.new()
    motion.position = Vector2(460,300)
    canvas._gui_input(motion)
    mouse.pressed = false
    mouse.position = Vector2(460,300)
    canvas._gui_input(mouse)
    assert(canvas.center.x < start.x, "one-finger/mouse drag")
    var previous_zoom: float = canvas.zoom
    var wheel := InputEventMouseButton.new()
    wheel.button_index=MOUSE_BUTTON_WHEEL_UP
    wheel.position=Vector2(350,240)
    wheel.pressed=true
    canvas._gui_input(wheel)
    assert(canvas.zoom>previous_zoom,"mouse wheel zoom")
    var t0 := InputEventScreenTouch.new()
    t0.index=0
    t0.pressed=true
    t0.position=Vector2(200,200)
    canvas._gui_input(t0)
    var t1 := InputEventScreenTouch.new()
    t1.index=1
    t1.pressed=true
    t1.position=Vector2(400,200)
    canvas._gui_input(t1)
    var before_pinch: float = canvas.zoom
    var drag := InputEventScreenDrag.new()
    drag.index=1
    drag.position=Vector2(480,200)
    canvas._gui_input(drag)
    assert(canvas.zoom>before_pinch,"pinch zoom")
    t0.pressed=false
    t1.pressed=false
    canvas._gui_input(t1)
    canvas._gui_input(t0)
    page.center_home()
    canvas._tap(canvas.size/2.0+Vector2(20.0,20.0))
    assert(page.panel.visible,"tap must open parcel panel")
    for i in range(30):
        await process_frame
        if not page.buy_button.disabled:
            break
    assert(not page.buy_button.disabled,"free parcel can be bought")
    var px: int = page.selected.x
    var py: int = page.selected.y
    page._confirm_purchase()
    assert(page.confirm.visible,"purchase confirmation")
    page.confirm.confirmed.emit()
    for i in range(45):
        await process_frame
        if purchased > 0:
            break
    assert(purchased==1,"wallet update signal")
    assert(mock.bought.has("%d,%d" % [px,py]),"server purchase called")
    print("world interaction smoke OK: drag, wheel, pinch, selection, confirmation, wallet refresh signal")
    page.queue_free()
    quit(0)
