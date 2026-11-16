extends SceneTree
const API = preload("res://world/api.gd")
const Stream = preload("res://world/stream.gd")
const Canvas = preload("res://world/map_canvas.gd")
const Mock = preload("res://tests/world_mock.gd")
var stream: Node
var canvas: Control
var mock: Node

func _initialize() -> void:
    call_deferred("_run")

func _event(num: int,kind: String,payload: Dictionary,obj: Variant = null) -> Dictionary:
    return {"event_id":num,"version":num,"kind":kind,"city_id":"ufa","cx":0,"cy":0,
        "chunks":[{"cx":0,"cy":0}],"object":obj,"payload":payload}

func _run() -> void:
    mock=Mock.new()
    root.add_child(mock)
    var api := API.new()
    root.add_child(api)
    api.mock = Callable(mock,"respond")
    stream=Stream.new()
    root.add_child(stream)
    stream.configure(api)
    canvas=Canvas.new()
    canvas.size=Vector2(700,380)
    root.add_child(canvas)
    canvas.attach(stream)
    stream.update_center(Vector2i(0,0),1)
    for i in range(120):
        if stream.chunks.has(Vector2i.ZERO):
            break
        await process_frame
    assert(stream.chunks.has(Vector2i.ZERO))
    var origin := Vector2i.ZERO
    var neighbour := Vector2i(1,0)
    assert(canvas._sprites.has(origin))
    assert(canvas._sprites.has(neighbour))
    var untouched: Node2D=canvas._sprites[neighbour]
    var count: int=canvas.texture_builds
    var obj := {"object_id":"enterprise:89","catalog_id":"bakery","owner_ref":"17",
        "stage_index":0,"x":4,"y":5,"w":2,"h":2,"color_rgb":10855585}
    var added := _event(1,"enterprise_construction",{"cells":[[4,5],[5,5],[4,6],[5,6]]},obj)
    stream._process_event(added)
    assert(stream._event_objects.has("enterprise:89"))
    assert(canvas._sprites[origin] == canvas._sprites[origin])
    assert(canvas._sprites[neighbour] == untouched)
    assert(canvas.texture_builds == count,"building rebuilt a chunk texture")
    assert(canvas._sprites[origin].event_cells.size() == 4)
    stream._process_event(_event(2,"enterprise_stage",added["payload"],obj))
    assert(canvas.texture_builds == count)
    stream._process_event(_event(3,"demolition",added["payload"],obj))
    assert(not stream._event_objects.has("enterprise:89"))
    assert(canvas._sprites[origin].event_cells.is_empty())
    stream._process_event(_event(4,"road_build",{"cells":[[7,7]]}))
    assert(stream.cell_at(7,7)["road"])
    stream._process_event(_event(5,"road_build",{"cells":[[7,7]],"removed":true}))
    assert(not stream.cell_at(7,7)["road"])
    assert(canvas._sprites[neighbour] == untouched)
    stream.cursor=5
    assert(stream._consume_page({"tip":6006,"reset":true,"events":[],"scanned":6006}) == "reset")
    assert(stream.cursor == 6006)
    stream.stop()
    mock.queue_free()
    print("world realtime smoke OK")
    quit(0)
