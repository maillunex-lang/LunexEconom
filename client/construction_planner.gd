extends RefCounted
## Client-only construction preview. Server must validate ownership, costs and zoning.
const ROAD = preload("res://road_network.gd")
var occupied: Dictionary = {}

func footprint(origin: Vector2i, size: Vector2i) -> Array[Vector2i]:
    var cells: Array[Vector2i] = []
    if size.x < 1 or size.y < 1 or size.x > 16 or size.y > 16:
        return cells
    for x in range(origin.x, origin.x + size.x):
        for y in range(origin.y, origin.y + size.y):
            cells.append(Vector2i(x, y))
    return cells

func preview(origin: Vector2i, size: Vector2i, roads: Object, world: Object) -> Dictionary:
    var cells := footprint(origin, size)
    if cells.is_empty():
        return {"ok": false, "reason": "invalid_size"}
    var adjacent_road := false
    for cell in cells:
        if absi(cell.x) > world.expansion_radius or absi(cell.y) > world.expansion_radius:
            return {"ok": false, "reason": "outside_explored_area"}
        if occupied.has(cell):
            return {"ok": false, "reason": "occupied"}
        if roads.is_road(cell):
            return {"ok": false, "reason": "road_overlap"}
        for delta in [Vector2i(0, -1), Vector2i(1, 0), Vector2i(0, 1), Vector2i(-1, 0)]:
            if roads.is_road(cell + delta):
                adjacent_road = true
    if not adjacent_road:
        return {"ok": false, "reason": "no_road_access"}
    return {"ok": true, "reason": "preview_only", "cells": cells}

func reserve_preview(cells: Array[Vector2i], object_id: String) -> bool:
    # Sandbox reservation only. Not a persisted or authoritative build.
    if object_id.is_empty() or cells.is_empty(): return false
    for cell in cells:
        if occupied.has(cell): return false
    for cell in cells:
        occupied[cell] = object_id
    return true

func clear_preview(object_id: String) -> void:
    for cell in occupied.keys():
        if occupied[cell] == object_id:
            occupied.erase(cell)
