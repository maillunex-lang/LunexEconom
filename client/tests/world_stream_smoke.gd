extends SceneTree
const API = preload("res://world/api.gd")
const Stream = preload("res://world/stream.gd")
const Mock = preload("res://tests/world_mock.gd")
var mock: Node
var api: Node
var stream: Node
var ready_events := 0
var growth_events := 0
var purchase_events := 0

func _initialize() -> void:
    call_deferred("_run")

func _until_chunks(count: int) -> void:
    for i in range(150):
        if stream.chunks.size() >= count:
            return
        await process_frame
    assert(false,"stream failed to load chunks")

func _run() -> void:
    mock = Mock.new()
    root.add_child(mock)
    api = API.new()
    root.add_child(api)
    api.mock = Callable(mock,"respond")
    stream = Stream.new()
    root.add_child(stream)
    stream.configure(api)
    stream.chunk_ready.connect(func(_key: Vector2i, _snapshot: Dictionary): ready_events+=1)
    stream.city_grew.connect(func(_event: Dictionary): growth_events+=1)
    stream.land_purchased.connect(func(_data: Dictionary): purchase_events+=1)
    assert(await stream.load_cities())
    assert(stream.cities.size()==20)
    stream.update_center(Vector2i(0,0),1)
    await _until_chunks(9)
    assert(stream.chunks.size()==9)
    assert(mock.max_parallel<=3 and mock.max_parallel>0)
    var first_ready := ready_events
    stream.revalidate(Vector2i(0,0))
    for i in range(6):
        await process_frame
    assert(mock.not_modified >= 1,"ETag/304 missing")
    assert(ready_events==first_ready,"304 unexpectedly redrew a chunk")
    mock.versions["0,0"]=1
    stream.revalidate(Vector2i(0,0))
    for i in range(6):
        await process_frame
    assert(ready_events==first_ready+1,"ETag version did not redraw")
    stream.update_center(Vector2i(240,240),1)
    await _until_chunks(9)
    assert(not stream.chunks.has(Vector2i(0,0)),"distant chunks not unloaded")
    stream.update_center(Vector2i(0,0),1)
    await _until_chunks(9)
    for i in range(6):
        await process_frame
    mock.failures_before_buy=3
    var unsuccessful: Dictionary = await stream.buy(0,0)
    assert(unsuccessful.get("code",0)==0)
    assert(stream.pending.has("0,0"),"pending id must survive a network outage")
    var first_id: String = mock.buy_ids[0]
    assert(first_id.begins_with("land."))
    var successful: Dictionary = await stream.buy(0,0)
    assert(successful.get("code",0)==201)
    for value in mock.buy_ids:
        assert(value == first_id,"retry changed purchase request_id")
    assert(purchase_events==1)
    for i in range(10):
        await process_frame
    assert(stream.parcel_at(0,0).get("owner_kind","")=="player")
    var growth := {"version":17,"kind":"city_growth","city_id":"ufa","payload":{"city":"ufa","old_radius":12,"new_radius":15,"new_level":2}}
    mock.growth_events.append(growth)
    stream.poll_events()
    for i in range(15):
        await process_frame
    assert(growth_events==1)
    assert(stream.cursor==17)
    assert(stream.cities[0].get("radius",0)==15)
    assert(stream.queued.size()+stream.loading.size()<=50)
    print("world stream smoke OK: 20 cities, cache/304, streaming, idempotent buy, city_growth, max HTTP=",mock.max_parallel)
    stream.stop()
    quit(0)
