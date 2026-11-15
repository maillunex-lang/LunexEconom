extends Node
signal chunk_ready(key: Vector2i, snapshot: Dictionary)
signal chunk_removed(key: Vector2i)
signal parcels_ready(key: Vector2i, data: Array)
signal city_grew(event: Dictionary)
signal enterprise_changed
signal network_error(code: String)
signal land_purchased(data: Dictionary)
signal road_built(data: Dictionary)
signal cities_ready
const Gen = preload("res://world/generator.gd")
const DeviceCache = preload("res://world/cache.gd")
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
var dirty: Dictionary = {}
var city_id := "ufa"
var device_cache: RefCounted
var _events_busy := false
var _poll_timer: Timer
var _session := 0

func _ready() -> void:
    _restore_pending()
    _poll_timer = Timer.new()
    _poll_timer.wait_time = 6.0
    _poll_timer.timeout.connect(poll_events)
    add_child(_poll_timer)

func configure(adapter: Node) -> void:
    api = adapter
    set_server(str(adapter.get("base_url")))

func set_server(base: String) -> void:
    var next_scope := base.sha256_text()
    if device_cache != null and device_cache.scope == next_scope:
        return
    stop()
    device_cache = DeviceCache.new()
    device_cache.set_server(base)
    cursor = device_cache.get_cursor()
    cities = device_cache.get_cities()
    cache.clear()
    parcels.clear()
    dirty.clear()

func set_city(id: String) -> void:
    if id == city_id:
        return
    city_id = id
    _session += 1
    queued.clear()
    loading.clear()
    active = 0
    desired.clear()
    for key in chunks.keys():
        chunk_removed.emit(key)
    chunks.clear()
    cache.clear()
    parcels.clear()
    dirty.clear()

func start() -> void:
    _poll_timer.start()

func stop() -> void:
    if _poll_timer != null:
        _poll_timer.stop()
    _session += 1
    desired.clear()
    queued.clear()
    loading.clear()
    active = 0
    for key in chunks.keys():
        chunk_removed.emit(key)
    chunks.clear()
    parcels.clear()

func load_cities() -> bool:
    if not cities.is_empty():
        refresh_cities()
        return true
    var response: Dictionary = await api.fetch("/world/cities")
    if int(response.get("code", 0)) != 200:
        network_error.emit("network")
        return false
    cities = response.get("data", {}).get("cities", [])
    if device_cache != null:
        device_cache.save_cities(cities)
    cities_ready.emit()
    return not cities.is_empty()

func refresh_cities() -> void:
    if api == null:
        return
    var result: Dictionary = await api.fetch("/world/cities")
    if int(result.get("code", 0)) != 200:
        return
    var latest: Array = result.get("data", {}).get("cities", [])
    if latest.is_empty():
        return
    cities = latest
    if device_cache != null:
        device_cache.save_cities(cities)
    cities_ready.emit()

func update_center(cell: Vector2i, radius: int) -> void:
    var cx := Gen.floor_div(cell.x, Gen.CHUNK)
    var cy := Gen.floor_div(cell.y, Gen.CHUNK)
    radius = clampi(radius, 1, 6)
    var next_desired := {}
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            next_desired[Vector2i(cx + dx, cy + dy)] = true
    desired = next_desired
    for key in chunks.keys():
        if not desired.has(key):
            chunks.erase(key)
            parcels.erase(key)
            chunk_removed.emit(key)
    queued = queued.filter(func(key: Vector2i): return desired.has(key))
    # Disk data appears in the very same frame, before the first HTTP request.
    for key in desired:
        if chunks.has(key):
            continue
        var old: Dictionary = cache.get(key, {})
        if old.is_empty() and device_cache != null:
            old = device_cache.get_chunk(city_id, key)
            if not old.is_empty():
                cache[key] = old
        if old.has("snapshot"):
            chunks[key] = old["snapshot"]
            chunk_ready.emit(key, chunks[key])
            if old.get("parcels", []) is Array and not old["parcels"].is_empty():
                parcels[key] = old["parcels"]
                parcels_ready.emit(key, parcels[key])
        if (old.is_empty() or dirty.has(key)) and not loading.has(key) and not queued.has(key):
            queued.append(key)
    queued.sort_custom(func(a: Vector2i, b: Vector2i) -> bool:
        return (a.x-cx)*(a.x-cx)+(a.y-cy)*(a.y-cy) < (b.x-cx)*(b.x-cx)+(b.y-cy)*(b.y-cy))
    _drain()

func _drain() -> void:
    while active < MAX_PARALLEL and not queued.is_empty():
        var key: Vector2i = queued.pop_front()
        if not desired.has(key) or loading.has(key):
            continue
        loading[key] = true
        active += 1
        _load_chunk(key, _session, city_id)

func _load_chunk(key: Vector2i, session: int, city: String) -> void:
    var old: Dictionary = cache.get(key, {})
    var tag: String = old.get("etag", "")
    var response: Dictionary = {}
    for attempt in range(3):
        response = await api.fetch("/world/chunk?cx=%d&cy=%d" % [key.x,key.y], HTTPClient.METHOD_GET, {}, tag)
        if session != _session:
            break
        var code := int(response.get("code", 0))
        if code == 304 and not old.has("snapshot"):
            tag = ""
            continue
        if code in [200, 304]:
            break
        if attempt < 2:
            await get_tree().create_timer(0.3 * pow(2.0, float(attempt))).timeout
    if session != _session:
        return
    var status := int(response.get("code", 0))
    if status == 200 and response.get("data", {}) is Dictionary:
        var snapshot: Dictionary = response["data"]
        if not snapshot.is_empty():
            var new_tag := str(response.get("etag", ""))
            if new_tag.is_empty():
                new_tag = str(snapshot.get("etag", ""))
            old = {"etag":new_tag, "snapshot":snapshot, "parcels":old.get("parcels", [])}
            cache[key] = old
    if status in [200,304] and old.has("snapshot"):
        if desired.has(key):
            var previous: Dictionary = chunks.get(key, {})
            var updated: Dictionary = old["snapshot"]
            if previous.is_empty() or int(previous.get("version", -1)) != int(updated.get("version", -1)):
                chunks[key] = updated
                chunk_ready.emit(key, updated)
            else:
                chunks[key] = updated
        if status == 200 or not parcels.has(key) or dirty.has(key):
            await _load_parcels(key, session, city)
        elif device_cache != null:
            device_cache.save_chunk(city, key, old)
        if session != _session:
            return
        dirty.erase(key)
    elif status not in [200, 304]:
        network_error.emit("network")
    if cache.size() > CACHE_LIMIT:
        for candidate in cache.keys():
            if not desired.has(candidate):
                cache.erase(candidate)
                break
    loading.erase(key)
    active = maxi(0, active - 1)
    _drain()

func _load_parcels(key: Vector2i, session: int, city: String) -> void:
    var response: Dictionary = await api.fetch("/land/parcels?chunk=%d,%d" % [key.x,key.y])
    if session != _session:
        return
    if int(response.get("code", 0)) == 200:
        var items: Array = response.get("data", {}).get("parcels", [])
        parcels[key] = items
        if cache.has(key):
            cache[key]["parcels"] = items
        if desired.has(key):
            parcels_ready.emit(key, items)
    if device_cache != null and cache.has(key):
        device_cache.save_chunk(city, key, cache[key])

func revalidate(key: Vector2i) -> void:
    dirty[key] = true
    if desired.has(key) and not loading.has(key) and not queued.has(key):
        queued.append(key)
        _drain()

func poll_events() -> void:
    if _events_busy or api == null or device_cache == null:
        return
    _events_busy = true
    for _batch in range(12):
        var response: Dictionary = await api.fetch("/world/events?after=%d" % cursor)
        if int(response.get("code", 0)) != 200:
            network_error.emit("network")
            break
        var data: Dictionary = response.get("data", {})
        var events: Array = data.get("events", [])
        for event in events:
            if event is Dictionary:
                _process_event(event)
                cursor = maxi(cursor, int(event.get("version", 0)))
        cursor = maxi(cursor, int(data.get("next_after", cursor)))
        device_cache.save_cursor(cursor)
        if events.size() < 100:
            break
    _events_busy = false

func _process_event(event: Dictionary) -> void:
    var kind := str(event.get("kind", ""))
    if kind == "city_growth":
        _apply_growth(event)
        return
    if kind in ["occupation", "demolition", "enterprise_stage", "enterprise_construction"]:
        enterprise_changed.emit()
    if kind not in ["land_buy", "road_build", "occupation", "demolition", "enterprise_stage", "enterprise_construction"]:
        return
    var impacted := _event_chunks(event)
    for key in impacted:
        if desired.has(key):
            revalidate(key)
        else:
            # Persisted cursor is safe: an unseen changed chunk cannot stay stale.
            cache.erase(key)
            if device_cache != null:
                device_cache.invalidate_chunk(city_id, key)

func _event_chunks(event: Dictionary) -> Dictionary:
    var output := {}
    if event.get("cx") != null and event.get("cy") != null:
        output[Vector2i(int(event["cx"]),int(event["cy"]))] = true
    var payload: Dictionary = event.get("payload", {})
    if payload.has("px") and payload.has("py"):
        output[Vector2i(Gen.floor_div(int(payload["px"]),2),Gen.floor_div(int(payload["py"]),2))] = true
    for cell in payload.get("cells", []):
        if cell is Array and cell.size() >= 2:
            output[Vector2i(Gen.floor_div(int(cell[0]),12),Gen.floor_div(int(cell[1]),12))] = true
    return output

func _apply_growth(event: Dictionary) -> void:
    var payload: Dictionary = event.get("payload", {})
    var updated_id := str(event.get("city_id", payload.get("city", "")))
    var previous_radius := int(payload.get("old_radius", 0))
    var next_radius := int(payload.get("new_radius", previous_radius))
    var middle := Vector2i.ZERO
    for city in cities:
        if str(city.get("id", "")) == updated_id:
            middle = Vector2i(int(city.get("x", 0)),int(city.get("y", 0)))
            city["radius"] = next_radius
            city["level"] = int(payload.get("new_level", city.get("level", 1)))
            break
    if device_cache != null:
        device_cache.save_cities(cities)
    # Invalidate the exact new ring, including offscreen disk snapshots.
    var affected := {}
    for y in range(middle.y-next_radius,middle.y+next_radius+1):
        for x in range(middle.x-next_radius,middle.x+next_radius+1):
            var distance := maxi(absi(x-middle.x),absi(y-middle.y))
            if distance>previous_radius and distance<=next_radius:
                affected[Vector2i(Gen.floor_div(x,12),Gen.floor_div(y,12))] = true
    for key in affected:
        if desired.has(key):
            revalidate(key)
        elif device_cache != null:
            cache.erase(key)
            device_cache.invalidate_chunk(updated_id,key)
    city_grew.emit(event)

func parcel_at(px: int, py: int) -> Dictionary:
    var key := Vector2i(Gen.floor_div(px, 2), Gen.floor_div(py, 2))
    for parcel in parcels.get(key, []):
        if int(parcel.get("px", 999999)) == px and int(parcel.get("py", 999999)) == py:
            return parcel
    return {}

func cell_at(x: int, y: int) -> Dictionary:
    var key := Vector2i(Gen.floor_div(x,12),Gen.floor_div(y,12))
    var snapshot: Dictionary = chunks.get(key, cache.get(key, {}).get("snapshot", {}))
    if snapshot.is_empty():
        return {}
    var xx := posmod(x,12)
    var yy := posmod(y,12)
    var terrain: Array = snapshot.get("terrain", [])
    var zones: Array = snapshot.get("zones", [])
    var roads: Array = snapshot.get("roads", [])
    var buildings: Array = snapshot.get("buildings", [])
    if yy >= terrain.size() or xx >= terrain[yy].size():
        return {}
    return {"terrain":str(terrain[yy][xx]),
        "zone":str(zones[yy][xx]) if yy < zones.size() and xx < zones[yy].size() else "free",
        "road":bool(roads[yy][xx]) if yy < roads.size() and xx < roads[yy].size() else false,
        "occupied":buildings[yy][xx] != null and str(buildings[yy][xx]) != "" if yy < buildings.size() and xx < buildings[yy].size() else false}

func road_near_parcel(px: int, py: int) -> bool:
    for y in range(py*6-1,py*6+7):
        for x in range(px*6-1,px*6+7):
            if bool(cell_at(x,y).get("road",false)):
                return true
    return false

func _pending_key(px: int, py: int) -> String:
    return "%d,%d" % [px,py]

func _restore_pending() -> void:
    var cfg := ConfigFile.new()
    if cfg.load(PENDING_PATH) == OK and cfg.has_section("requests"):
        for key in cfg.get_section_keys("requests"):
            pending[key] = str(cfg.get_value("requests",key,""))

func _save_pending() -> void:
    var cfg := ConfigFile.new()
    for key in pending:
        cfg.set_value("requests",key,pending[key])
    cfg.save(PENDING_PATH)

func buy(px: int, py: int) -> Dictionary:
    var key := _pending_key(px,py)
    if not pending.has(key):
        pending[key] = "land." + Crypto.new().generate_random_bytes(16).hex_encode()
        _save_pending()
    var response: Dictionary = {}
    for attempt in range(3):
        response = await api.fetch("/land/buy", HTTPClient.METHOD_POST,
            {"px":px,"py":py,"request_id":pending[key]})
        var status := int(response.get("code", 0))
        if status in [200,201] or (status >= 400 and status < 500):
            break
        if attempt < 2:
            await get_tree().create_timer(0.3 * pow(2.0, float(attempt))).timeout
    var status := int(response.get("code", 0))
    if status in [200,201]:
        pending.erase(key)
        _save_pending()
        var chunk := Vector2i(Gen.floor_div(px,2),Gen.floor_div(py,2))
        await _load_parcels(chunk,_session,city_id)
        revalidate(chunk)
        land_purchased.emit(response.get("data", {}))
    elif status >= 400 and status < 500 and status != 429:
        pending.erase(key)
        _save_pending()
    return response

func build_road(cells: Array) -> Dictionary:
    var values: Array = []
    for cell in cells:
        if cell is Vector2i:
            values.append([cell.x,cell.y])
    if values.is_empty():
        return {"code":400,"data":{"error":"invalid_road_cells"}}
    var key := "road:" + JSON.stringify(values).sha256_text()
    if not pending.has(key):
        pending[key] = "road." + Crypto.new().generate_random_bytes(16).hex_encode()
        _save_pending()
    # Server POST /world/roads currently ignores request_id. INSERT uses
    # ON CONFLICT DO NOTHING; retries don't create duplicate road rows.
    var response: Dictionary = await api.fetch("/world/roads",HTTPClient.METHOD_POST,
        {"cells":values,"request_id":pending[key]})
    if int(response.get("code", 0)) == 200:
        pending.erase(key)
        _save_pending()
        for cell in cells:
            revalidate(Vector2i(Gen.floor_div(cell.x,12),Gen.floor_div(cell.y,12)))
        road_built.emit(response.get("data", {}))
    elif int(response.get("code", 0)) >= 400 and int(response.get("code", 0)) < 500:
        pending.erase(key)
        _save_pending()
    return response
