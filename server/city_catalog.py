"""Catalog of city objects (Expansion 1.0, stage 1): housing, education, health, administration, green and transport objects.

Design data only: nothing here can be built yet. The catalog is the single source of the parameters that later blocks (land and ownership,
construction with materials and stages, households, the city development director) read, so a number is changed in one place. All money is
integer roubles, all quantities integer units, wear in permille. Parameters are starting targets of the game balance and are meant to be
tuned (docs/EXPANSION_1_0.md). Existing building kinds, sizes and economics are not changed; `legacy_kind` links an entry to one.
"""
VERSION = 1

# Construction stages: share (permille) of the build time, in order; each has its own 3D visual (client/world3d, docs/WORLD3D.md).
STAGES = (("foundation", 200), ("frame", 350), ("finishing", 300), ("commissioning", 150))

# Structure type: materials per resident (or per unit of capacity), wear per month in permille of condition, how well it keeps its price.
STRUCTURES = {
    "wood": {"materials": {"timber": 8}, "wear": 6},
    "brick": {"materials": {"stone": 8, "cement": 2, "timber": 1}, "wear": 3},
    "panel": {"materials": {"cement": 3, "steel": 1, "stone": 2}, "wear": 4},
    "monolith": {"materials": {"cement": 4, "steel": 2}, "wear": 2},
    "public": {"materials": {"stone": 4, "cement": 2, "steel": 1}, "wear": 3},
    "light": {"materials": {"timber": 2, "stone": 1}, "wear": 5},
    "ground": {"materials": {"stone": 1}, "wear": 4},
}

# id, name, category, (w, h), structure, capacity, cost per unit of capacity (roubles), jobs, upkeep per month, floors, legacy kind
HOUSING = (
    ("house_wood", "Деревянный дом", "housing", (1, 1), "wood", 4, 15000, 0, 400, 1, None),
    ("house_brick", "Кирпичный дом", "housing", (1, 1), "brick", 5, 18000, 0, 500, 1, None),
    ("cottage", "Коттедж", "housing", (2, 2), "brick", 6, 40000, 0, 900, 2, None),
    ("townhouse", "Таунхаус", "housing", (2, 3), "brick", 32, 35000, 1, 6000, 2, None),
    ("block_2", "МКД, 2 этажа", "housing", (2, 2), "brick", 36, 30000, 1, 5500, 2, None),
    ("block_3", "МКД, 3 этажа", "housing", (2, 2), "brick", 54, 28000, 1, 8000, 3, None),
    ("block_5", "Пятиэтажка", "housing", (2, 3), "panel", 180, 24000, 2, 24000, 5, None),
    ("block_9", "Девятиэтажка", "housing", (2, 3), "panel", 324, 21000, 3, 40000, 9, None),
    ("block_12", "Дом 12 этажей", "housing", (3, 3), "monolith", 540, 20000, 4, 62000, 12, None),
    ("block_16", "Дом 16 этажей", "housing", (3, 3), "monolith", 768, 19000, 5, 85000, 16, None),
    ("complex_modern", "Современный жилой комплекс", "housing", (4, 4), "monolith", 1200, 22000, 12, 150000, 20, None),
    ("quarter", "Жилой квартал", "housing", (6, 6), "monolith", 2400, 20000, 25, 280000, 16, None),
)

# id, name, category, (w, h), structure, served population, build cost, jobs, upkeep per month, legacy kind
MUNICIPAL = (
    ("kindergarten", "Детский сад", "education", (2, 2), "public", 150, 300000, 12, 12000, None),
    ("school", "Школа", "education", (3, 2), "public", 600, 400000, 6, 3000, "school"),
    ("lyceum", "Лицей", "education", (3, 3), "public", 700, 650000, 30, 26000, None),
    ("college", "Колледж", "education", (3, 3), "public", 900, 900000, 40, 34000, None),
    ("university", "Университет", "education", (4, 4), "public", 3000, 3500000, 150, 140000, None),
    ("fap", "ФАП", "health", (1, 2), "light", 800, 120000, 3, 6000, None),
    ("polyclinic", "Поликлиника", "health", (3, 2), "public", 6000, 700000, 40, 45000, None),
    ("hospital", "Больница", "health", (3, 3), "public", 10000, 800000, 8, 5000, "hospital"),
    ("administration", "Администрация", "administration", (3, 2), "public", 20000, 600000, 25, 30000, None),
    ("police", "Полиция", "administration", (2, 2), "public", 15000, 400000, 18, 22000, None),
    ("fire_depot", "Пожарное депо", "administration", (2, 3), "public", 20000, 500000, 20, 26000, None),
    ("park", "Парк", "green", (2, 2), "ground", 3000, 150000, 2, 1000, "park"),
    ("square", "Сквер", "green", (1, 1), "ground", 800, 40000, 0, 500, None),
    ("playground", "Детская площадка", "green", (1, 1), "ground", 600, 30000, 0, 400, None),
    ("sports", "Спортивное сооружение", "green", (3, 2), "public", 2500, 450000, 10, 18000, None),
    ("bus_stop", "Остановка", "transport", (1, 1), "light", 1500, 25000, 0, 300, None),
    ("bus_station", "Автовокзал", "transport", (3, 2), "public", 8000, 550000, 20, 28000, None),
    ("parking", "Парковка", "transport", (2, 2), "ground", 400, 60000, 1, 800, None),
    ("landscaping", "Благоустройство", "amenity", (1, 1), "ground", 1000, 20000, 0, 300, None),
)

# Starting build time in game months by number of cells (larger projects take longer, never less than one month).
def build_months(cells):
    if cells <= 2:
        return 1
    if cells <= 4:
        return 2
    if cells <= 9:
        return 3
    if cells <= 16:
        return 6
    return 9


def _materials(structure, units):
    return {name: per * units for name, per in STRUCTURES[structure]["materials"].items()}


def _entry(oid, name, category, size, structure, capacity, unit_cost, jobs, upkeep, extra):
    cells = size[0] * size[1]
    return {
        "id": oid, "name": name, "category": category, "w": size[0], "h": size[1], "cells": cells,
        "structure": structure, "capacity": capacity,
        "build_cost": capacity * unit_cost if category == "housing" else unit_cost,
        "materials": _materials(structure, capacity if category == "housing" else max(cells * 12, 1)),
        "jobs": jobs, "upkeep": upkeep, "wear_permille_per_month": STRUCTURES[structure]["wear"],
        "build_months": build_months(cells), "zone": "city",
        "model": oid, "stage_models": [s for s, _ in STAGES], **extra,
    }


def _build():
    out = {}
    for oid, name, category, size, structure, capacity, unit_cost, jobs, upkeep, floors, legacy in HOUSING:
        out[oid] = _entry(oid, name, category, size, structure, capacity, unit_cost, jobs, upkeep,
                          {"kind": "residential", "floors": floors, "legacy_kind": legacy, "households": max(capacity // 3, 1)})
    for oid, name, category, size, structure, served, cost, jobs, upkeep, legacy in MUNICIPAL:
        out[oid] = _entry(oid, name, category, size, structure, served, cost, jobs, upkeep,
                          {"kind": "municipal", "floors": 1, "legacy_kind": legacy, "households": 0})
    return out


CATALOG = _build()


def get(object_id):
    return CATALOG.get(object_id)


def view():
    """GET /catalog/city: public, cacheable, read-only. `enabled` is false until the construction blocks land."""
    return {"version": VERSION, "enabled": False, "stages": [{"id": s, "share_permille": p} for s, p in STAGES],
            "structures": {k: {"materials_per_unit": v["materials"], "wear_permille_per_month": v["wear"]} for k, v in STRUCTURES.items()},
            "objects": [CATALOG[k] for k in CATALOG],
            "note": "Starting balance targets; nothing here is buildable yet (docs/EXPANSION_1_0.md)."}
