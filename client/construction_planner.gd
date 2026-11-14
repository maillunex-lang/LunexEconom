extends RefCounted
## Client-only construction preview. Server must validate ownership, costs and zoning.
const ROAD = preload("res://road_network.gd")
const DIRS := [Vector2i(0, -1), Vector2i(1, 0), Vector2i(0, 1), Vector2i(-1, 0)]
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
    for cell in cells:
        if absi(cell.x) > world.expansion_radius or absi(cell.y) > world.expansion_radius:
            return {"ok": false, "reason": "outside_explored_area"}
        if occupied.has(cell):
            return {"ok": false, "reason": "occupied"}
        if world.server_cells.has(cell):
            return {"ok": false, "reason": "server_occupied"}
        if roads.is_road(cell):
            return {"ok": false, "reason": "road_overlap"}
        if world.cell_kind(cell.x, cell.y) == 4:
            return {"ok": false, "reason": "water"}
    var access := find_access_path(cells, roads, world)
    if access.is_empty() and not _touches_road(cells, roads):
        return {"ok": false, "reason": "no_road_access"}
    return {"ok": true, "reason": "preview_only", "cells": cells, "access": access}

func _touches_road(cells: Array[Vector2i], roads: Object) -> bool:
    for cell in cells:
        for delta in DIRS:
            if roads.is_road(cell + delta):
                return true
    return false

func _is_free(cell: Vector2i, footprint_set: Dictionary, roads: Object, world: Object) -> bool:
    if footprint_set.has(cell) or occupied.has(cell) or world.server_cells.has(cell):
        return false
    if absi(cell.x) > world.expansion_radius or absi(cell.y) > world.expansion_radius:
        return false
    return roads.is_road(cell) or world.cell_kind(cell.x, cell.y) != 4

## Shortest orthogonal path (BFS) from the footprint edge to the nearest road.
## Returns [] when the footprint already touches a road or nothing is reachable.
## Path order: first cell touches the building, last cell is an existing road.
func find_access_path(cells: Array[Vector2i], roads: Object, world: Object, max_visited: int = 6000) -> Array[Vector2i]:
    if _touches_road(cells, roads):
        return []
    var footprint_set: Dictionary = {}
    for cell in cells: footprint_set[cell] = true
    var previous: Dictionary = {}
    var queue: Array[Vector2i] = []
    for cell in cells:
        for delta in DIRS:
            var start: Vector2i = cell + delta
            if not previous.has(start) and _is_free(start, footprint_set, roads, world):
                previous[start] = start
                queue.append(start)
    var head := 0
    while head < queue.size() and head < max_visited:
        var current: Vector2i = queue[head]
        head += 1
        if roads.is_road(current):
            var path: Array[Vector2i] = []
            var cursor := current
            while previous[cursor] != cursor:
                path.push_front(cursor)
                cursor = previous[cursor]
            path.push_front(cursor)
            return path
        for delta in DIRS:
            var next: Vector2i = current + delta
            if not previous.has(next) and _is_free(next, footprint_set, roads, world):
                previous[next] = current
                queue.append(next)
    return []

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
