extends Node
## Network calls use the existing world adapter for auth renewal and test mocks.
const PENDING_PATH := "user://enterprise_pending.cfg"
var transport: Node
var pending: Dictionary = {}

func configure(adapter: Node) -> void:
    transport = adapter
    var cfg := ConfigFile.new()
    if cfg.load(PENDING_PATH) == OK:
        pending = cfg.get_value("requests", "items", {})

func _persist() -> void:
    var cfg := ConfigFile.new()
    cfg.set_value("requests", "items", pending)
    cfg.save(PENDING_PATH)

func _request_id() -> String:
    return "enterprise:%s" % str(Crypto.new().generate_random_bytes(16).hex_encode())

func create(building_id: String, px: int, py: int, x: int, y: int) -> Dictionary:
    var key := "%s:%d:%d:%d:%d" % [building_id, px, py, x, y]
    if not pending.has(key):
        pending[key] = {"request_id": _request_id(), "building_id": building_id, "px": px, "py": py, "x": x, "y": y}
        _persist()
    var response: Dictionary = await transport.fetch("/enterprises", HTTPClient.METHOD_POST, pending[key])
    if int(response.get("code", 0)) >= 200 and int(response.get("code", 0)) < 300:
        pending.erase(key)
        _persist()
    return response

func list_own() -> Dictionary:
    return await transport.fetch("/enterprises")

func detail(id: int) -> Dictionary:
    return await transport.fetch("/enterprises/%d" % id)

func report(id: int) -> Dictionary:
    return await transport.fetch("/enterprises/%d/report" % id)

func settings(id: int, values: Dictionary) -> Dictionary:
    return await transport.fetch("/enterprises/%d/settings" % id, HTTPClient.METHOD_POST, values)

func sell(id: int) -> Dictionary:
    var key := "sell:%d" % id
    if not pending.has(key):
        pending[key] = {"request_id": _request_id()}
        _persist()
    var response: Dictionary = await transport.fetch("/enterprises/%d/sell" % id, HTTPClient.METHOD_POST, pending[key])
    if int(response.get("code", 0)) == 200:
        pending.erase(key)
        _persist()
    return response
