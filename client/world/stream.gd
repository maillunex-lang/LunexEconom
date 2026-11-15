extends Node
signal chunk_ready(key: Vector2i, snapshot: Dictionary)
signal chunk_removed(key: Vector2i)
signal parcels_ready(key: Vector2i, data: Array)
signal city_grew(event: Dictionary)
signal network_error(code: String)
signal land_purchased(data: Dictionary)
const Gen = preload("res://world/generator.gd")
const PENDING_PATH := "user://world_pending_buys.cfg"
const MAX_PARALLEL := 3
const CACHE_LIMIT := 96
var api: Node
var chunks: Dictionary = {}
var cache: Dictionary = {}
var parcels: Dictionary = {}
var desired: Dictionary = {}
var queued: Array[Vector2i] = []
var loading: Dictionary = {}
var active := 0
var cursor := 0
var cities: Array = []
var pending: Dictionary = {}
var _events_busy := false
var _poll_timer: Timer
var _session := 0

func _ready() -> void:
    _restore_pending()
    _poll_timer = Timer.new()
    _poll_timer.wait_time = 8.0
    _poll_timer.autostart = false
    _poll_timer.timeout.connect(poll_events)
    add_child(_poll_timer)

func configure(adapter: Node) -> void:
    api = adapter

func start() -> void:
    _poll_timer.start()

func stop() -> void:
    _poll_timer.stop()
    _session += 1
    desired.clear()
    queued.clear()
    loading.clear()
    active = 0
    for key in chunks.keys():
        chunk_removed.emit(key)
    chunks.clear()

func load_cities() -> bool:
    var response: Dictionary = await api.fetch("/world/cities")
    if response.get("code", 0) != 200:
        network_error.emit("network")
        return false
    cities = response.get("data", {}).get("cities", [])
    return true

func update_center(cell: Vector2i, radius: int) -> void:
    var cx := Gen.floor_div(cell.x, Gen.CHUNK)
    var cy := Gen.floor_div(cell.y, Gen.CHUNK)
    radius = clampi(radius, 1, 6)
    var next_desired := {}
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            var key := Vector2i(cx + dx, cy + dy)
            next_desired[key] = true
    desired = next_desired
    for key in chunks.keys():
        if not desired.has(key):
            chunks.erase(key)
            parcels.erase(key)
            chunk_removed.emit(key)
    queued = queued.filter(func(key: Vector2i): return desired.has(key))
    for key in desired:
        if not chunks.has(key) and not loading.has(key) and not queued.has(key):
            queued.append(key)
    queued.sort_custom(func(a: Vector2i,b: Vector2i):
        return (a.x-cx)*(a.x-cx)+(a.y-cy)*(a.y-cy) < (b.x-cx)*(b.x-cx)+(b.y-cy)*(b.y-cy))
    _drain()

func _drain() -> void:
    while active < MAX_PARALLEL and not queued.is_empty():
        var key: Vector2i = queued.pop_front()
        if not desired.has(key) or loading.has(key):
            continue
        loading[key] = true
        active += 1
        _load_chunk(key, _session)

func _load_chunk(key: Vector2i, session: int) -> void:
    var path := "/world/chunk?cx=%d&cy=%d" % [key.x,key.y]
    var old: Dictionary = cache.get(key, {})
    var tag: String = old.get("etag", "")
    var response: Dictionary
    for attempt in range(3):
        response = await api.fetch(path, HTTPClient.METHOD_GET, {}, tag)
        if session != _session:
            break
        var code: int = response.get("code", 0)
        if code == 304 and old.is_empty():
            tag = ""
            continue
        if code == 200 or code == 304:
            break
        if attempt < 2:
            await get_tree().create_timer(0.3 * pow(2.0, float(attempt))).timeout
    if session == _session:
        var code: int = response.get("code", 0)
        if code == 200 and response.get("data", {}) is Dictionary:
            var snapshot: Dictionary = response["data"]
            if not snapshot.is_empty():
                var new_tag: String = response.get("etag", "")
                if new_tag.is_empty():
                    new_tag = str(snapshot.get("etag", ""))
                cache[key] = {"etag": new_tag, "snapshot": snapshot}
                old = cache[key]
        if code == 200 or code == 304:
            if desired.has(key) and old.has("snapshot"):
                var previous: Dictionary = chunks.get(key, {})
                var updated: Dictionary = old["snapshot"]
                if previous.is_empty() or int(previous.get("version", -1)) != int(updated.get("version", -1)):
                    chunks[key] = updated
                    chunk_ready.emit(key, updated)
                else:
                    chunks[key] = updated
                if code == 200 or not parcels.has(key):
                    await _load_parcels(key, session)
        else:
            network_error.emit("network")
        if cache.size() > CACHE_LIMIT:
            for candidate in cache.keys():
                if not desired.has(candidate):
                    cache.erase(candidate)
                    break
    if session == _session:
        loading.erase(key)
        active = maxi(0, active - 1)
        _drain()

func _load_parcels(key: Vector2i, session: int) -> void:
    var response: Dictionary = await api.fetch("/land/parcels?chunk=%d,%d" % [key.x, key.y])
    if session == _session and response.get("code", 0) == 200:
        var items: Array = response.get("data", {}).get("parcels", [])
        parcels[key] = items
        if desired.has(key):
            parcels_ready.emit(key, items)

func revalidate(key: Vector2i) -> void:
    if desired.has(key) and not loading.has(key) and not queued.has(key):
        queued.append(key)
        _drain()

func poll_events() -> void:
    if _events_busy or api == null:
        return
    _events_busy = true
    var response: Dictionary = await api.fetch("/world/events?after=%d" % cursor)
    _events_busy = false
    if response.get("code", 0) != 200:
        network_error.emit("network")
        return
    var data: Dictionary = response.get("data", {})
    for event in data.get("events", []):
        cursor = maxi(cursor, int(event.get("version", 0)))
        if event.get("kind", "") == "city_growth":
            _apply_growth(event)
        elif event.get("kind", "") in ["land_buy", "road_build", "occupation", "demolition", "enterprise_stage"]:
            var key := Vector2i(int(event.get("cx", 0)), int(event.get("cy", 0)))
            if desired.has(key):
                revalidate(key)
    cursor = maxi(cursor, int(data.get("next_after", cursor)))

func _apply_growth(event: Dictionary) -> void:
    var payload: Dictionary = event.get("payload", {})
    var city_id: String = str(event.get("city_id", payload.get("city", "")))
    for i in range(cities.size()):
        if str(cities[i].get("id", "")) == city_id:
            cities[i]["radius"] = int(payload.get("new_radius", cities[i].get("radius", 12)))
            cities[i]["level"] = int(payload.get("new_level", cities[i].get("level", 1)))
            break
    for key in desired.keys():
        revalidate(key)
    city_grew.emit(event)

func parcel_at(px: int, py: int) -> Dictionary:
    var chunk := Vector2i(Gen.floor_div(px, 2), Gen.floor_div(py, 2))
    for parcel in parcels.get(chunk, []):
        if int(parcel.get("px", 999999)) == px and int(parcel.get("py", 999999)) == py:
            return parcel
    return {}

func _pending_key(px: int, py: int) -> String:
    return "%d,%d" % [px, py]

func _restore_pending() -> void:
    var cfg := ConfigFile.new()
    if cfg.load(PENDING_PATH) == OK:
        for key in cfg.get_section_keys("requests") if cfg.has_section("requests") else []:
            pending[key] = str(cfg.get_value("requests", key, ""))

func _save_pending() -> void:
    var cfg := ConfigFile.new()
    for key in pending:
        cfg.set_value("requests", key, pending[key])
    cfg.save(PENDING_PATH)

func buy(px: int, py: int) -> Dictionary:
    var key := _pending_key(px, py)
    if not pending.has(key):
        pending[key] = "land." + Crypto.new().generate_random_bytes(16).hex_encode()
        _save_pending()
    var payload := {"px": px, "py": py, "request_id": pending[key]}
    var response: Dictionary = {}
    for attempt in range(3):
        response = await api.fetch("/land/buy", HTTPClient.METHOD_POST, payload)
        var code: int = response.get("code", 0)
        if code in [200,201] or (code >= 400 and code < 500):
            break
        if attempt < 2:
            await get_tree().create_timer(0.3 * pow(2.0, float(attempt))).timeout
    var code: int = response.get("code", 0)
    if code in [200,201]:
        pending.erase(key)
        _save_pending()
        var chunk := Vector2i(Gen.floor_div(px, 2), Gen.floor_div(py, 2))
        parcels.erase(chunk)
        _load_parcels(chunk, _session)
        revalidate(chunk)
        land_purchased.emit(response.get("data", {}))
    elif code >= 400 and code < 500 and code != 429:
        pending.erase(key)
        _save_pending()
    return response
