extends SceneTree
const Canvas = preload("res://world/map_canvas.gd")
const Stream = preload("res://world/stream.gd")
const Adapter = preload("res://world/api.gd")
const Mock = preload("res://tests/world_mock.gd")
func _initialize() -> void:
    call_deferred("_run")
func _run() -> void:
    var canvas := Canvas.new()
    root.add_child(canvas)
    canvas.size = Vector2(1280,720)
    var stream := Stream.new()
    root.add_child(stream)
    var adapter := Adapter.new()
    root.add_child(adapter)
    var mock := Mock.new()
    root.add_child(mock)
    adapter.mock = Callable(mock,"respond")
    stream.configure(adapter)
    canvas.attach(stream)
    var terrain: Array = []
    var zones: Array = []
    var roads: Array = []
    var buildings: Array = []
    for y in range(12):
        var t: Array = []
        var z: Array = []
        var r: Array = []
        var b: Array = []
        for x in range(12):
            t.append("ground")
            z.append("industrial")
            r.append(false)
            b.append("enterprise:1" if x < 2 and y < 2 else null)
        terrain.append(t)
        zones.append(z)
        roads.append(r)
        buildings.append(b)
    canvas._on_chunk(Vector2i.ZERO,{"terrain":terrain,"zones":zones,"roads":roads,"buildings":buildings})
    assert(canvas.building_cells[Vector2i.ZERO].size() == 4)
    canvas.preview = {"x":0,"y":0,"width":2,"height":2}
    canvas.queue_redraw()
    assert(canvas.preview.width == 2)
    canvas._on_removed(Vector2i.ZERO)
    assert(canvas.building_cells.is_empty())
    print("enterprise map smoke OK: occupied footprint preview chunk invalidation")
    quit(0)
