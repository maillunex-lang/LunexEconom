extends Node
## Client adapter for the production, supply and retail chain endpoints.
var transport: Node

func configure(adapter: Node) -> void:
    transport = adapter

func detail(id: int) -> Dictionary:
    return await transport.fetch("/enterprises/%d" % id)

func supply(id: int) -> Dictionary:
    return await transport.fetch("/enterprises/%d/supply" % id)

func save_supply(id: int, links: Array) -> Dictionary:
    return await transport.fetch("/enterprises/%d/supply" % id, HTTPClient.METHOD_PUT, {"links": links})

func market(city: String, product: String = "") -> Dictionary:
    var path := "/market/%s" % city.uri_encode()
    if not product.is_empty():
        path += "?product=" + product.uri_encode()
    return await transport.fetch(path)

func market_history(city: String, product: String) -> Dictionary:
    return await transport.fetch("/market/history?city=%s&product=%s" % [city.uri_encode(), product.uri_encode()])

func cells(id: int) -> Dictionary:
    return await transport.fetch("/enterprises/%d/cells" % id)

func save_cells(id: int, cells_value: Array) -> Dictionary:
    return await transport.fetch("/enterprises/%d/cells" % id, HTTPClient.METHOD_PUT, {"cells": cells_value})

func sales(id: int, day_from: int = 0, day_to: int = 1) -> Dictionary:
    return await transport.fetch("/enterprises/%d/sales?day_from=%d&day_to=%d" % [id, day_from, day_to])

func ratings(city: String, good: String) -> Dictionary:
    return await transport.fetch("/retail/ratings?city=%s&good=%s" % [city.uri_encode(), good.uri_encode()])
