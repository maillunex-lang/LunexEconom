extends Node
## Polling-based prototype: authoritative server events, per-chunk version and gap recovery.
signal sync_status(message: String)
const ROOT := "https://rikagro.ru/lunexeconom/api/"
var world: Node
var cursor := 0
var busy := false
var versions: Dictionary = {}
var pending: Array[Vector2i] = []
var syncing_chunk := false
var timer: Timer

func _ready() -> void:
    timer = Timer.new()
    timer.wait_time = 3.0
    timer.autostart = true
    add_child(timer)
    timer.timeout.connect(poll)
    poll()

func poll() -> void:
    if busy or syncing_chunk or not pending.is_empty(): return
    busy = true
    var req := HTTPRequest.new()
    req.timeout = 8
    add_child(req)
    req.request_completed.connect(func(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
        busy = false
        req.queue_free()
        if result != HTTPRequest.RESULT_SUCCESS or code != 200: 
            sync_status.emit("Синхронизация: сеть недоступна")
            return
        var data = JSON.parse_string(body.get_string_from_utf8())
        if not data is Dictionary or not data.get("events", null) is Array: return
        for event in data["events"]:
            if not event is Dictionary: continue
            var seq := int(event.get("seq", -1))
            if seq != cursor + 1:
                # Missing event or restarted server: invalidate known versions and request snapshots.
                for coord in versions.keys(): _schedule_snapshot(coord)
                cursor = maxi(cursor, seq - 1)
            var coord := Vector2i(int(event.get("cx", 0)), int(event.get("cy", 0)))
            var previous := int(versions.get(coord, 0))
            var version := int(event.get("version", -1))
            if version != previous + 1:
                _schedule_snapshot(coord)
            elif not pending.has(coord):
                if str(event.get("kind", "")) == "terrain_changed":
                    _load_terrain(coord)
                world.apply_server_event(event)
                versions[coord] = version
            cursor = seq
        if not pending.is_empty(): _load_next_snapshot()
        elif bool(data.get("has_more", false)): poll.call_deferred()
        sync_status.emit("Мир синхронизирован · событие %d" % cursor)
    )
    if not GameSession.is_authenticated():
        busy = false
        req.queue_free()
        sync_status.emit("Для синхронизации требуется вход в аккаунт")
        return
    var headers := PackedStringArray(["Authorization: Bearer " + GameSession.access_token])
    if req.request(ROOT + "events?after=" + str(cursor), headers) != OK:
        busy = false
        req.queue_free()

func _schedule_snapshot(coord: Vector2i) -> void:
    if not pending.has(coord): pending.append(coord)

func _load_next_snapshot() -> void:
    if syncing_chunk or pending.is_empty(): return
    syncing_chunk = true
    var coord := pending[0]
    var req := HTTPRequest.new()
    req.timeout = 8
    add_child(req)
    req.request_completed.connect(func(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
        req.queue_free()
        syncing_chunk = false
        if result != HTTPRequest.RESULT_SUCCESS or code != 200: return
        var data = JSON.parse_string(body.get_string_from_utf8())
        if not data is Dictionary or not data.get("cells", null) is Array: return
        world.apply_chunk_snapshot(coord, data["cells"])
        _load_terrain(coord)
        versions[coord] = int(data.get("version", 0))
        pending.pop_front()
        if not pending.is_empty(): _load_next_snapshot.call_deferred()
    )
    if not GameSession.is_authenticated():
        syncing_chunk = false
        req.queue_free()
        return
    var headers := PackedStringArray(["Authorization: Bearer " + GameSession.access_token])
    if req.request(ROOT + "chunk?cx=" + str(coord.x) + "&cy=" + str(coord.y), headers) != OK:
        syncing_chunk = false
        req.queue_free()

func _load_terrain(coord: Vector2i) -> void:
    if not GameSession.is_authenticated(): return
    var req := HTTPRequest.new()
    req.timeout = 8
    add_child(req)
    req.request_completed.connect(func(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
        req.queue_free()
        if result != HTTPRequest.RESULT_SUCCESS or code != 200: return
        var data = JSON.parse_string(body.get_string_from_utf8())
        if data is Dictionary and data.get("edits", null) is Array:
            world.set_terrain_edits(coord, data["edits"])
    )
    var headers := PackedStringArray(["Authorization: Bearer " + GameSession.access_token])
    if req.request(ROOT + "terrain/chunk?cx=" + str(coord.x) + "&cy=" + str(coord.y), headers) != OK:
        req.queue_free()