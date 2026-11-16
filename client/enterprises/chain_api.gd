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
    var inputs: Dictionary = {}
    for item in links:
        var product := str(item.get("product_id", ""))
        if product.is_empty():
            continue
        if not inputs.has(product):
            inputs[product] = []
        inputs[product].append({"source_type":item.get("source_type", "market"),
            "source_enterprise_id":item.get("source_enterprise_id", null),
            "share":int(item.get("share", 1000)), "priority":int(item.get("priority", 1)),
            "max_price":int(item.get("max_price", 0)), "min_quality":int(item.get("min_quality", 0))})
    return await transport.fetch("/enterprises/%d/supply" % id, HTTPClient.METHOD_PUT, {"inputs": inputs})

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

func sales_policy(id: int, product: String) -> Dictionary:
    return await transport.fetch("/enterprises/%d/sales-policy/%s" % [id, product.uri_encode()])

func save_sales_policy(id: int, product: String, values: Dictionary) -> Dictionary:
    return await transport.fetch("/enterprises/%d/sales-policy/%s" % [id, product.uri_encode()], HTTPClient.METHOD_PUT, values)

func offers(city: String, product: String) -> Dictionary:
    return await transport.fetch("/supply/offers?city=%s&product=%s" % [city.uri_encode(),product.uri_encode()])
