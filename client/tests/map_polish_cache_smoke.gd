extends SceneTree
const API = preload("res://world/api.gd")
const Stream = preload("res://world/stream.gd")
const Mock = preload("res://tests/world_mock.gd")
var mock: Node
var api: Node
var ready_events := 0

func _initialize() -> void:
    call_deferred("_run")

func _offline(_path: String, _method: int, _body: Dictionary, _headers: PackedStringArray) -> Dictionary:
    return {"code":0,"data":{}}

func _until_loaded(stream: Node, count: int) -> void:
    for i in range(240):
        if stream.chunks.size()>=count and stream.parcels.size()>=count:
            return
        await process_frame
    assert(false,"cache smoke: chunks/parcels failed to load")

func _run() -> void:
    mock=Mock.new()
    root.add_child(mock)
    api=API.new()
    api.base_url="https://cache-v207c.invalid/api"
    root.add_child(api)
    api.mock=Callable(mock,"respond")
    var first := Stream.new()
    root.add_child(first)
    first.configure(api)
    assert(await first.load_cities())
    first.update_center(Vector2i.ZERO,1)
    await _until_loaded(first,9)
    var cache_file: String=first.device_cache._chunk_path("ufa",Vector2i.ZERO)
    assert(FileAccess.file_exists(cache_file),"no on-device chunk file")
    var debug_chunk: Dictionary = first.device_cache.get_chunk("ufa",Vector2i.ZERO)
    assert(not debug_chunk.is_empty(),"invalid disk chunk")
    first.stop()
    first.queue_free()
    api.mock=Callable(self,"_offline")
    var offline := Stream.new()
    root.add_child(offline)
    offline.configure(api)
    assert(await offline.load_cities(),"offline city list unavailable")
    offline.update_center(Vector2i.ZERO,1)
    assert(offline.chunks.size()==9,"offline map must appear synchronously from disk")
    assert(offline.parcels.size()==9,"cached parcel owners missing")
    offline.stop()
    offline.queue_free()
    var damaged := FileAccess.open(cache_file,FileAccess.WRITE)
    damaged.store_string("{definitely broken")
    damaged.close()
    api.mock=Callable(mock,"respond")
    var restored := Stream.new()
    root.add_child(restored)
    restored.configure(api)
    restored.chunk_ready.connect(func(_key: Vector2i,_data: Dictionary): ready_events+=1)
    assert(await restored.load_cities())
    mock.calls.clear()
    restored.update_center(Vector2i.ZERO,1)
    assert(not restored.chunks.has(Vector2i.ZERO),"corrupt disk cache was incorrectly trusted")
    await _until_loaded(restored,9)
    assert(not restored.device_cache.get_chunk("ufa",Vector2i.ZERO).is_empty(),"corrupt file did not recover")
    restored.cursor=0
    restored.device_cache.save_cursor(0)
    var before := ready_events
    mock.calls.clear()
    mock.versions["0,0"]=4
    mock.growth_events.append({"version":10,"kind":"land_buy","cx":0,"cy":0,"payload":{}})
    await restored.poll_events()
    for i in range(24):
        await process_frame
    var chunk_requests: Array=mock.calls.filter(func(path: String) -> bool: return path.begins_with("/world/chunk"))
    assert(chunk_requests.size()==1 and chunk_requests[0].contains("cx=0&cy=0"),"event refreshed unrelated chunks")
    assert(ready_events==before+1,"changed chunk must produce exactly one redraw")
    before=ready_events
    mock.calls.clear()
    var not_modified_before: int=mock.not_modified
    mock.growth_events.append({"version":11,"kind":"land_buy","cx":0,"cy":0,"payload":{}})
    await restored.poll_events()
    for i in range(24):
        await process_frame
    assert(mock.not_modified>not_modified_before,"If-None-Match was not sent")
    assert(ready_events==before,"304 unexpectedly repainted cached chunk")
    restored.stop()
    restored.queue_free()
    print("map polish cache smoke OK: disk offline immediate, owners, corrupt recovery, event-only chunk, 304 no repaint")
    quit(0)
