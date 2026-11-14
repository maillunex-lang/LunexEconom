"""Twenty deterministic *game* regions of Bashkortostan over the existing map.

No database, no terrain/roads mutation. Real locations and approximate 2024
city populations are static reference labels, not simulated economic residents.
"""
from functools import lru_cache
import hashlib
import heapq
import math
import roads

SEED = 18273
UFA_LAT, UFA_LON = 54.7431, 55.9678
CELLS_PER_KM = 3.0
NORTH_KM_PER_DEG = 111.195
EAST_KM_PER_DEG = NORTH_KM_PER_DEG * math.cos(math.radians(UFA_LAT))

# id, city name, latitude, longitude, approximate 01.01.2024 residents,
# and a non-binding future-industry *tag*.
CITY_DATA = (
    ("ufa", "Уфа", 54.7431, 55.9678, 1163300, "управление, нефтехимия"),
    ("sterlitamak", "Стерлитамак", 53.6246, 55.9501, 280500, "химия, машиностроение"),
    ("salavat", "Салават", 53.3837, 55.9077, 146600, "нефтехимия"),
    ("neftekamsk", "Нефтекамск", 56.0920, 54.2661, 134000, "машиностроение"),
    ("oktyabrsky", "Октябрьский", 54.4815, 53.4710, 116400, "нефть, сервис"),
    ("beloretsk", "Белорецк", 53.9631, 58.3981, 63700, "металлургия"),
    ("sibay", "Сибай", 52.7181, 58.6658, 55900, "добыча, металлургия"),
    ("meleuz", "Мелеуз", 52.9647, 55.9328, 55200, "агро, переработка"),
    ("kumertau", "Кумертау", 52.7667, 55.7833, 57300, "машиностроение"),
    ("tuymazy", "Туймазы", 54.6067, 53.7097, 67800, "нефть, агро"),
    ("ishimbay", "Ишимбай", 53.4545, 56.0415, 62700, "нефть, промышленность"),
    ("birsk", "Бирск", 55.4211, 55.5428, 44800, "агро, образование"),
    ("belebey", "Белебей", 54.1167, 54.1167, 58800, "машиностроение, агро"),
    ("dyurtyuli", "Дюртюли", 55.4911, 54.8688, 31100, "агро, логистика"),
    ("baymak", "Баймак", 52.5933, 58.3225, 17600, "агро, добыча"),
    ("uchaly", "Учалы", 54.3581, 59.4361, 36100, "горнодобыча"),
    ("davlekanovo", "Давлеканово", 54.2215, 55.0343, 21200, "агро, переработка"),
    ("blagoveshchensk", "Благовещенск", 55.0350, 55.9781, 35200, "химия, логистика"),
    ("agidel", "Агидель", 55.9077, 53.9355, 13700, "энергетика"),
    ("yanaul", "Янаул", 56.2751, 54.9338, 25400, "лес, логистика"),
)

STREET_NAMES = (
    "ул. Ленина", "ул. Салавата Юлаева", "просп. Октября",
    "ул. Мира", "ул. Советская", "ул. Дружбы", "ул. Мустая Карима",
    "ул. Агидель", "ул. Башкортостана", "ул. Курая",
    "ул. Шайхзады Бабича", "ул. Нефтяников", "ул. Зелёная",
    "ул. Молодёжная", "ул. Уральская", "ул. Полевая",
    "ул. Строителей", "мкр. Нефтяник", "мкр. Южный",
)

DIRECTIONS = (
    (1, 0, 1000), (0, 1, 1000), (-1, 0, 1000), (0, -1, 1000),
    (1, 1, 1414), (-1, 1, 1414), (1, -1, 1414), (-1, -1, 1414),
)


def _seed(text):
    return int.from_bytes(hashlib.sha256(("%s:%s" % (SEED, text)).encode()).digest()[:8], "big")


def _nearest_dry(x, y):
    if not roads.is_water(x, y):
        return x, y
    # Nearest by Euclidean distance, then stable coordinate order.
    for radius in range(1, 26):
        ring = [
            (x + dx, y + dy)
            for dx in range(-radius, radius + 1)
            for dy in range(-radius, radius + 1)
            if max(abs(dx), abs(dy)) == radius
        ]
        for px, py in sorted(ring, key=lambda pt: ((pt[0]-x)**2+(pt[1]-y)**2, pt[0], pt[1])):
            if not roads.is_water(px, py):
                return px, py
    raise RuntimeError("No dry center within 25 cells")


def _grid_point(lat, lon):
    x = round((lon - UFA_LON) * EAST_KM_PER_DEG * CELLS_PER_KM)
    y = round((UFA_LAT - lat) * NORTH_KM_PER_DEG * CELLS_PER_KM)
    return _nearest_dry(x, y)


@lru_cache(maxsize=1)
def _city_tuple():
    result = []
    for id_, name, lat, lon, residents, tag in CITY_DATA:
        x, y = _grid_point(lat, lon)
        radius = max(12, min(65, round(8 + math.sqrt(residents / 1000) * 1.6)))
        result.append({
            "id": id_, "name": name, "region": name + " (игровой регион)",
            "lat": lat, "lon": lon,
            "x": x, "y": y, "population_estimate": residents,
            "population_label": "оценка на 01.01.2024",
            "specialization": tag, "radius": radius,
        })
    return tuple(result)


def cities():
    """Return fresh JSON-friendly records, safe for callers to mutate."""
    return [{**city, "streets": streets(city),
             "monthly_growth_permille": ((_seed(city["id"]) % 11) - 5) / 25.0}
            for city in _city_tuple()]


def regions():
    return [
        {"id": "region_" + city["id"], "name": city["region"],
         "center_city_id": city["id"], "game_region": True}
        for city in _city_tuple()
    ]


def get_city(city_id):
    return next((dict(c) for c in _city_tuple() if c["id"] == city_id), None)


def city_area(city):
    return {"x": city["x"], "y": city["y"], "radius": city["radius"]}


def city_for_cell(x, y):
    nearest = None
    for city in _city_tuple():
        d2 = (x - city["x"]) ** 2 + (y - city["y"]) ** 2
        if d2 <= city["radius"] ** 2 and (nearest is None or d2 < nearest[0]):
            nearest = d2, city
    return dict(nearest[1]) if nearest is not None else None


def population(city, month_index):
    """Reference-only estimate, independent of player economy, bounded 80-120%."""
    month = max(0, int(month_index))
    drift = (_seed(city["id"]) % 11 - 5) / 25000.0
    factor = max(0.8, min(1.2, 1.0 + month * drift))
    return round(city["population_estimate"] * factor)


def streets(city):
    return sorted(STREET_NAMES, key=lambda name: _seed(city["id"] + ":" + name))


def plot_address(city, x, y):
    index = ((x - city["x"]) * 13 + (y - city["y"]) * 17) % len(STREET_NAMES)
    street = streets(city)[index]
    return "%s, %s, %d:%d" % (city["name"], street, x, y)


def distance_km(a, b):
    r = 6371.0088
    lat1, lat2 = math.radians(a["lat"]), math.radians(b["lat"])
    delta_lat = lat2 - lat1
    delta_lon = math.radians(b["lon"] - a["lon"])
    h = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))


WATER_PENALTY = 8


def _path(start, goal):
    """Deterministic eight-neighbor A*: stays on the existing dry terrain."""
    if start == goal:
        return [start]
    sx, sy = start
    gx, gy = goal
    min_x, max_x = min(sx, gx) - 35, max(sx, gx) + 35
    min_y, max_y = min(sy, gy) - 35, max(sy, gy) + 35

    def heuristic(x, y):
        dx, dy = abs(x - gx), abs(y - gy)
        return 1000 * max(dx, dy) + 414 * min(dx, dy)

    queue = [(heuristic(sx, sy), 0, sx, sy)]
    best = {start: 0}
    previous = {}
    expanded = 0
    while queue:
        _, cost, x, y = heapq.heappop(queue)
        point = (x, y)
        if cost != best.get(point):
            continue
        if point == goal:
            out = [point]
            while out[-1] != start:
                out.append(previous[out[-1]])
            out.reverse()
            return out
        expanded += 1
        if expanded > 200_000:
            break
        for dx, dy, step in DIRECTIONS:
            nx, ny = x + dx, y + dy
            if not (min_x <= nx <= max_x and min_y <= ny <= max_y):
                continue
            candidate = (nx, ny)
            next_cost = cost + step * (WATER_PENALTY if roads.is_water(nx, ny) else 1)       # a highway crosses the river by a bridge, never along it
            if next_cost >= best.get(candidate, 2 ** 62):
                continue
            best[candidate] = next_cost
            previous[candidate] = point
            heapq.heappush(queue, (next_cost + heuristic(nx, ny), next_cost, nx, ny))
    raise RuntimeError("Could not find dry highway route")


def _graph_edges():
    cities = _city_tuple()
    possible = sorted(
        (distance_km(cities[i], cities[j]), i, j)
        for i in range(len(cities)) for j in range(i+1, len(cities))
    )
    parent = list(range(len(cities)))

    def find(v):
        while parent[v] != v:
            v = parent[v]
        return v

    chosen = []
    for _, i, j in possible:
        a, b = find(i), find(j)
        if a != b:
            parent[a] = b
            chosen.append((i, j))
        if len(chosen) == len(cities) - 1:
            break
    for _, i, j in possible:
        if (i, j) not in chosen:
            chosen.append((i, j))
            if len(chosen) == len(cities) - 1 + 8:
                break
    return chosen


@lru_cache(maxsize=1)
def _route_tuple():
    cities = _city_tuple()
    result = []
    for i, j in _graph_edges():
        a, b = cities[i], cities[j]
        cells = _path((a["x"], a["y"]), (b["x"], b["y"]))
        length = sum((1.41421356 if u[0] != v[0] and u[1] != v[1] else 1.0)
                     for u, v in zip(cells, cells[1:])) / CELLS_PER_KM
        result.append({
            "from": a["id"], "to": b["id"],
            "distance_km": round(distance_km(a, b), 1),
            "road_km": round(length, 1),
            "travel_months": max(0.01, round(length / 1800.0, 3)),
            "cells": cells,
        })
    return tuple(result)


def routes():
    return [{**route, "cells": [[x, y] for x, y in route["cells"]]} for route in _route_tuple()]
