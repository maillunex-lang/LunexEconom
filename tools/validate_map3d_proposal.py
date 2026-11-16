#!/usr/bin/env python3
"""Валидатор предложения «Карта 3D». Целые числа, без секретов, без сети."""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent / "sim" / "data" / "map3d_proposed"
REQUIRED = ("event.schema.json", "examples.json", "budgets.json", "limits.json")
BUILDING_TYPES = {"building_added", "building_removed", "building_stage_changed"}
KIND_FOR_TYPE = {
    "building_added": {"enterprise_construction", "occupation"},
    "building_removed": {"demolition"},
    "building_stage_changed": {"enterprise_stage"},
    "road_added": {"road_build"},
    "road_removed": {"road_build"},
    "parcel_owner_changed": {"land_buy"},
    "city_growth": {"city_growth"},
    "terrain_edit": {"terrain_edit"},
}
TERRAIN = {"ground", "tree", "water"}
OWNERS = {"city", "state", "company", "player"}
SECRET_KEYS = {"password", "token", "email", "secret", "authorization"}
STAGES = ("foundation", "frame", "finishing", "commissioning", "operational")
ONLINE = (50, 500, 5000)


def load_json(name):
    path = BASE / name
    if not path.exists():
        raise SystemExit(f"FAIL: файл {name} отсутствует")
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def check_numbers(value, path=""):
    """Запрещает float. bool — отдельный тип JSON, не целое число игры."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        raise SystemExit(f"FAIL: float запрещён в {path}")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise SystemExit(f"FAIL: ключ не строка в {path}")
            check_numbers(item, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            check_numbers(item, f"{path}[{index}]")
        return
    raise SystemExit(f"FAIL: неожиданный тип в {path}")


def compact_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _fail(errors, message):
    errors.append(f"FAIL: {message}")


def schema_type_ok(value, expected):
    if isinstance(expected, list):
        return any(schema_type_ok(value, item) for item in expected)
    if expected == "integer":
        return type(value) is int
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return type(value) is bool
    if expected == "null":
        return value is None
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    return False


def resolve_ref(schema, node):
    if isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"]
        if not ref.startswith("#/"):
            raise SystemExit(f"FAIL: внешняя ссылка схемы {ref}")
        target = schema
        for part in ref[2:].split("/"):
            target = target[part]
        return target
    return node


def validate_schema(schema, node, value, path, errors):
    node = resolve_ref(schema, node)
    if "oneOf" in node:
        matched = 0
        for option in node["oneOf"]:
            nested = []
            validate_schema(schema, option, value, path, nested)
            if not nested:
                matched += 1
        if matched != 1:
            _fail(errors, f"{path} не подходит ровно под одну ветку oneOf")
        return
    expected = node.get("type")
    if expected is not None and not schema_type_ok(value, expected):
        _fail(errors, f"{path} имеет неверный тип")
        return
    if isinstance(value, str):
        if "minLength" in node and len(value) < node["minLength"]:
            _fail(errors, f"{path} короче минимума")
        if "maxLength" in node and len(value) > node["maxLength"]:
            _fail(errors, f"{path} длиннее максимума")
        if "enum" in node and value not in node["enum"]:
            _fail(errors, f"{path} вне enum")
    if type(value) is int:
        if "minimum" in node and value < node["minimum"]:
            _fail(errors, f"{path} меньше минимума")
        if "maximum" in node and value > node["maximum"]:
            _fail(errors, f"{path} больше максимума")
    if isinstance(value, list):
        if "minItems" in node and len(value) < node["minItems"]:
            _fail(errors, f"{path} слишком короткий список")
        if "maxItems" in node and len(value) > node["maxItems"]:
            _fail(errors, f"{path} слишком длинный список")
        if "items" in node:
            for index, item in enumerate(value):
                validate_schema(schema, node["items"], item, f"{path}[{index}]", errors)
    if isinstance(value, dict):
        required = node.get("required", [])
        for key in required:
            if key not in value:
                _fail(errors, f"{path} без поля {key}")
        properties = node.get("properties", {})
        if node.get("additionalProperties") is False:
            extra = [key for key in value if key not in properties]
            if extra:
                _fail(errors, f"{path} лишние поля {extra}")
        for key, item in value.items():
            if key in properties:
                validate_schema(schema, properties[key], item, f"{path}.{key}", errors)


def reject_secrets(value, path, errors):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in SECRET_KEYS:
                _fail(errors, f"секретное поле {path}.{key}")
            reject_secrets(item, f"{path}.{key}", errors)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_secrets(item, f"{path}[{index}]", errors)


def cells_of(event):
    raw = event.get("payload", {}).get("cells", [])
    parsed = []
    for item in raw:
        if not isinstance(item, list) or len(item) != 2 or type(item[0]) is not int or type(item[1]) is not int:
            return None
        parsed.append((item[0], item[1]))
    return parsed


def chunk_of_cell(x, y):
    return (x // 12 if x >= 0 else -(( -x + 11) // 12),
            y // 12 if y >= 0 else -(( -y + 11) // 12))


def check_event(event, limits, catalog_ids, errors, label):
    if event["event_id"] != event["version"]:
        _fail(errors, f"{label} event_id и version различаются")
    kind = event["kind"]
    if kind not in KIND_FOR_TYPE[event["type"]]:
        _fail(errors, f"{label} kind {kind} не соответствует type {event['type']}")
    listed = {(item["cx"], item["cy"]) for item in event["chunks"]}
    if len(listed) != len(event["chunks"]):
        _fail(errors, f"{label} повторяет чанк")
    if len(event["chunks"]) == 1:
        only = event["chunks"][0]
        if event["cx"] != only["cx"] or event["cy"] != only["cy"]:
            _fail(errors, f"{label} cx/cy не совпали с единственным чанком")
    elif event["cx"] is not None or event["cy"] is not None:
        _fail(errors, f"{label} при нескольких чанках cx/cy должны быть null")
    obj = event["object"]
    if event["type"] in BUILDING_TYPES:
        if not isinstance(obj, dict):
            _fail(errors, f"{label} без объекта здания")
            return
        if len(obj["object_id"].encode("utf-8")) > limits["max_object_id_bytes"]:
            _fail(errors, f"{label} слишком длинный object_id")
        if catalog_ids is not None and obj["catalog_id"] not in catalog_ids:
            _fail(errors, f"{label} неизвестный catalog_id {obj['catalog_id']}")
        rectangle = {(obj["x"] + dx, obj["y"] + dy) for dx in range(obj["w"]) for dy in range(obj["h"])}
        got = cells_of(event)
        if got is None or set(got) != rectangle or len(got) != len(rectangle):
            _fail(errors, f"{label} клетки не совпали со следом здания")
        stage = event["payload"].get("stage")
        if stage is not None and stage != STAGES[obj["stage_index"]]:
            _fail(errors, f"{label} имя стадии не совпало с stage_index")
    elif obj is not None:
        _fail(errors, f"{label} object должен быть null")
    if event["type"] in {"road_added", "road_removed"}:
        got = cells_of(event)
        if not got or len(got) > limits["max_cells_per_event"] or len(set(got)) != len(got):
            _fail(errors, f"{label} неверные клетки дороги")
        removed = event.get("removed") is True or event["payload"].get("removed") is True
        if event["type"] == "road_removed" and not removed:
            _fail(errors, f"{label} снос дороги без removed")
        if event["type"] == "road_added" and removed:
            _fail(errors, f"{label} постройка дороги помечена removed")
    if event["type"] == "parcel_owner_changed":
        payload = event["payload"]
        if type(payload.get("px")) is not int or type(payload.get("py")) is not int:
            _fail(errors, f"{label} участок без целых px/py")
        elif (payload["px"] // 2, payload["py"] // 2) not in listed and not event.get("chunks_truncated"):
            _fail(errors, f"{label} чанк участка не перечислен")
        if payload.get("owner_kind") not in OWNERS:
            _fail(errors, f"{label} неизвестный owner_kind")
    if event["type"] == "city_growth":
        payload = event["payload"]
        needed = ("old_level", "new_level", "old_radius", "new_radius")
        if any(type(payload.get(key)) is not int for key in needed):
            _fail(errors, f"{label} рост без целых радиусов")
        elif payload["new_level"] != payload["old_level"] + 1 or payload["new_radius"] <= payload["old_radius"]:
            _fail(errors, f"{label} рост не увеличивает уровень и радиус")
        if payload.get("city") != event["city_id"]:
            _fail(errors, f"{label} город роста не совпал")
    if event["type"] == "terrain_edit":
        payload = event["payload"]
        if payload.get("terrain") not in TERRAIN or type(payload.get("x")) is not int or type(payload.get("y")) is not int:
            _fail(errors, f"{label} правка рельефа неполная")
        elif cells_of(event) != [(payload["x"], payload["y"])]:
            _fail(errors, f"{label} клетка правки не совпала")
    if event["type"] != "city_growth" or not event.get("chunks_truncated"):
        got = cells_of(event) or []
        for x, y in got:
            if chunk_of_cell(x, y) not in listed:
                _fail(errors, f"{label} клетка {(x, y)} вне перечисленных чанков")


def apply_one(buildings, roads, event):
    kind = event["type"]
    if kind == "building_added":
        obj = event["object"]
        previous = buildings.get(obj["object_id"])
        if previous is not None and (previous["x"], previous["y"], previous["w"], previous["h"], previous["catalog_id"]) != (
            obj["x"], obj["y"], obj["w"], obj["h"], obj["catalog_id"]
        ):
            return "conflict"
        buildings[obj["object_id"]] = obj
        return None
    if kind == "building_stage_changed":
        obj = event["object"]
        if obj["object_id"] not in buildings:
            return "missing_object"
        buildings[obj["object_id"]] = obj
        return None
    if kind == "building_removed":
        if event["object"]["object_id"] not in buildings:
            return "missing_object"
        del buildings[event["object"]["object_id"]]
        return None
    if kind == "road_added":
        roads.update(cells_of(event))
        return None
    if kind == "road_removed":
        cells = cells_of(event)
        if any(cell not in roads for cell in cells):
            return "missing_road"
        for cell in cells:
            roads.remove(cell)
        return None
    return None


def apply_sequence(steps):
    last_id = None
    last_body = None
    buildings = {}
    roads = set()
    ids = [event["event_id"] for event in steps]
    if any(nxt < prev for prev, nxt in zip(ids, ids[1:])):
        return "out_of_order"
    for event in steps:
        event_id = event["event_id"]
        if last_id is not None and event_id == last_id:
            if event != last_body:
                return "replay_conflict"
            continue
        reason = apply_one(buildings, roads, event)
        if reason:
            return reason
        last_id = event_id
        last_body = event
    return "apply"


def plan_catchup(case, max_gap):
    last = case["last"]
    tip = case["tip"]
    scanned = case["scanned"]
    event_ids = list(case["events"])
    if type(last) is not int or type(tip) is not int or type(scanned) is not int or type(case["reset"]) is not bool:
        return "protocol_error"
    if any(type(item) is not int for item in event_ids):
        return "protocol_error"
    if case["reset"]:
        return "snapshot"
    if tip < last or scanned < 0:
        return "protocol_error"
    if tip - last > max_gap:
        return "snapshot"
    if event_ids != sorted(event_ids) or len(event_ids) != len(set(event_ids)):
        return "protocol_error"
    if any(item < last for item in event_ids):
        return "protocol_error"
    fresh = [item for item in event_ids if item > last]
    if not fresh:
        if scanned >= tip:
            return "ignore" if tip == last else "advance"
        return "catchup"
    if fresh[0] > last + 1 and scanned < fresh[0] - 1:
        return "catchup"
    if scanned < fresh[-1]:
        return "catchup"
    return "apply"


def check_budgets(budgets, errors):
    time_box = budgets["time"]
    if not (time_box["first_picture_warm_cache_ms"]
            < time_box["first_picture_cold_local_terrain_ms"]
            < time_box["first_picture_hq_network_budget_ms"]):
        _fail(errors, "бюджет первой картинки не возрастает от кеша к сети")
    render = budgets["render"]
    if render["min_fps"] > render["target_fps"]:
        _fail(errors, "минимум кадров выше цели")
    if not (render["max_building_triangles_lod2"]
            < render["max_building_triangles_lod1"]
            < render["max_building_triangles_lod0"]
            < render["max_triangles_per_frame"]):
        _fail(errors, "LOD треугольников не убывает с расстоянием")
    if not (render["lod0_cells"] < render["lod1_cells"] < render["lod2_cells"]):
        _fail(errors, "дистанции LOD не возрастают")
    if render["camera_min_height_m"] >= render["camera_max_height_m"]:
        _fail(errors, "диапазон камеры пуст")
    traffic = budgets["traffic"]
    idle = traffic["idle_responses_per_hour"]
    event_bytes = traffic["assumed_event_bytes"]
    idle_bytes = traffic["assumed_idle_bytes"]
    for online in ONLINE:
        share = traffic[f"viewport_share_permille_{online}"]
        world = traffic[f"world_events_per_hour_{online}"]
        relevant = world * share // 1000
        if traffic[f"relevant_events_per_hour_{online}"] != relevant:
            _fail(errors, f"доля видимых событий для {online} не сходится")
        expected_bytes = relevant * event_bytes + idle * idle_bytes
        if traffic[f"client_bytes_per_hour_{online}"] != expected_bytes:
            _fail(errors, f"трафик клиента для {online} не сходится")
        expected_responses = online * (relevant + idle)
        if traffic[f"server_responses_per_hour_{online}"] != expected_responses:
            _fail(errors, f"число ответов для {online} не сходится")
        if traffic[f"websocket_db_queries_per_hour_{online}"] != world:
            _fail(errors, f"запросы БД websocket для {online} не равны числу событий")


def positive_integers(value, path, errors):
    if isinstance(value, dict):
        for key, item in value.items():
            positive_integers(item, f"{path}.{key}", errors)
        return
    if isinstance(value, str):
        return
    if type(value) is int and value > 0:
        return
    _fail(errors, f"{path} не положительное целое")


def main():
    errors = []
    try:
        schema = load_json("event.schema.json")
        examples = load_json("examples.json")
        budgets = load_json("budgets.json")
        limits = load_json("limits.json")
        for name, data in (
            ("event.schema.json", schema),
            ("examples.json", examples),
            ("budgets.json", budgets),
            ("limits.json", limits),
        ):
            check_numbers(data, name)
    except SystemExit as exc:
        print(exc)
        return 1
    for label, data in (("examples", examples), ("budgets", budgets), ("limits", limits)):
        if data.get("balance") != "draft":
            _fail(errors, f"{label} без пометки balance draft")
    positive_integers({key: value for key, value in limits.items() if key != "balance"}, "limits", errors)
    positive_integers({key: value for key, value in budgets.items() if key != "balance"}, "budgets", errors)
    check_budgets(budgets, errors)
    catalog_path = Path(__file__).resolve().parents[1] / "server" / "data" / "buildings.json"
    catalog_ids = None
    if catalog_path.exists():
        with catalog_path.open(encoding="utf-8") as handle:
            catalog = json.load(handle)
        catalog_ids = {item["id"] for item in catalog}
    events = examples.get("events", [])
    if not 6 <= len(events) <= 8:
        _fail(errors, f"примеров событий {len(events)}, нужно 6–8")
    by_id = {}
    previous = 0
    for event in events:
        validate_schema(schema, schema, event, f"event {event.get('event_id')}", errors)
        reject_secrets(event, "event", errors)
        if type(event.get("event_id")) is int:
            if event["event_id"] <= previous:
                _fail(errors, "event_id примеров не строго возрастают")
            previous = event["event_id"]
            by_id[event["event_id"]] = event
        if errors:
            continue
        check_event(event, limits, catalog_ids, errors, f"событие {event.get('event_id')}")
        if len(compact_bytes(event)) > limits["max_event_bytes"]:
            _fail(errors, f"событие {event.get('event_id')} больше лимита байт")
    idle = {"events": [], "next_after": 0, "tip": 0, "reset": False, "scanned": 0}
    if len(compact_bytes(idle)) > limits["idle_response_max_bytes"]:
        _fail(errors, "пустой ответ длиннее лимита")
    for sequence in examples.get("sequences", []):
        missing = [step for step in sequence["steps"] if step not in by_id]
        if missing:
            _fail(errors, f"последовательность {sequence['id']} ссылается на неизвестные id")
            continue
        result = apply_sequence([by_id[step] for step in sequence["steps"]])
        if result != sequence["expect"]:
            _fail(errors, f"последовательность {sequence['id']}: ждали {sequence['expect']}, получили {result}")
    for case in examples.get("catchup", []):
        result = plan_catchup(case, limits["catchup_max_gap"])
        if result != case["expect"]:
            _fail(errors, f"догонка {case['id']}: ждали {case['expect']}, получили {result}")
    if errors:
        print("\n".join(errors))
        return 1
    print("OK: предложение карты 3D сходится (balance: draft)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
