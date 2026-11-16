"""Районы города и слои дохода. Числа только из JSON, balance: draft."""
from __future__ import annotations

import json
from pathlib import Path


def ufa_path() -> Path:
    return Path(__file__).resolve().parent.joinpath("data", "districts_ufa.json")


def split_largest_remainder(total: int, weights: list[int], keys: list[str]) -> list[int]:
    """Деление вниз и перенос остатка. Сумма долей равна total, если есть положительный вес.

    Порядок остатка: больший (total * вес % сумма_весов), затем ключ по возрастанию.
    Нулевой вес остаток не получает. Так же, как розница делит спрос (docs/retail.md).
    """
    count = len(weights)
    if count != len(keys):
        raise RuntimeError("ключи и веса разной длины")
    if total < 0:
        raise RuntimeError("отрицательная сумма")
    parts = [0] * count
    weight_sum = 0
    for weight in weights:
        if isinstance(weight, bool) or not isinstance(weight, int) or weight < 0:
            raise RuntimeError("вес должен быть целым неотрицательным")
        weight_sum += weight
    if total == 0 or weight_sum == 0:
        return parts
    for index, weight in enumerate(weights):
        parts[index] = total * weight // weight_sum
    left = total - sum(parts)
    eligible = [index for index, weight in enumerate(weights) if weight > 0]
    eligible.sort(key=lambda index: (-(total * weights[index] % weight_sum), keys[index]))
    cursor = 0
    while left > 0:
        parts[eligible[cursor % len(eligible)]] += 1
        left -= 1
        cursor += 1
    return parts


def _reject_loose(value, label: str) -> None:
    if isinstance(value, bool):
        raise RuntimeError(f"булево в {label}")
    if type(value).__name__ == "float":
        raise RuntimeError(f"дробь в {label}")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise RuntimeError(f"ключ не строка в {label}")
            _reject_loose(item, label + "." + key)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_loose(item, f"{label}[{index}]")
        return
    if isinstance(value, (int, str)):
        return
    raise RuntimeError(f"недопустимое значение в {label}")


def _need_int(row: dict, key: str, label: str, low: int | None = None, high: int | None = None) -> int:
    if key not in row or isinstance(row[key], bool) or not isinstance(row[key], int):
        raise RuntimeError(f"{label}.{key} должно быть целым")
    value = row[key]
    if low is not None and value < low:
        raise RuntimeError(f"{label}.{key} ниже {low}")
    if high is not None and value > high:
        raise RuntimeError(f"{label}.{key} выше {high}")
    return value


def _shares(raw, layer_ids: list[str], label: str) -> dict[str, int]:
    if not isinstance(raw, dict):
        raise RuntimeError(f"{label} не объект")
    if set(raw) != set(layer_ids):
        raise RuntimeError(f"{label} не совпадает со слоями")
    shares = {}
    for layer_id in layer_ids:
        value = raw[layer_id]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RuntimeError(f"{label}.{layer_id} должно быть целым неотрицательным")
        shares[layer_id] = value
    if sum(shares.values()) != 1000:
        raise RuntimeError(f"{label} в сумме не 1000")
    return shares


def load_city_districts(path: Path | None = None) -> dict:
    source = path or ufa_path()
    book = json.loads(source.read_text(encoding="utf-8"))
    _reject_loose(book, source.name)
    if book.get("balance") != "draft":
        raise RuntimeError("числа районов должны быть помечены balance: draft")
    if not isinstance(book.get("city_id"), str) or not book["city_id"]:
        raise RuntimeError("city_id пуст")
    _need_int(book, "ad_factor_permille", "city", 0)
    _need_int(book, "competition_s", "city", 1, 4)
    _need_int(book, "growth_bp", "city", 0)
    layers = book.get("layers")
    districts = book.get("districts")
    if not isinstance(layers, list) or len(layers) != 4:
        raise RuntimeError("нужны четыре слоя дохода")
    if not isinstance(districts, list) or not districts:
        raise RuntimeError("нет районов")
    layer_ids = []
    for layer in layers:
        if not isinstance(layer, dict):
            raise RuntimeError("слой не объект")
        layer_id = layer.get("id")
        if not isinstance(layer_id, str) or not layer_id:
            raise RuntimeError("пустой id слоя")
        if not isinstance(layer.get("name"), str) or not layer["name"]:
            raise RuntimeError(f"слой {layer_id} без имени")
        _need_int(layer, "income_index_permille", layer_id, 0)
        for key in (
            "basket_food_permille",
            "basket_clothes_permille",
            "basket_fuel_permille",
            "basket_electronics_permille",
        ):
            _need_int(layer, key, layer_id, 0)
        layer_ids.append(layer_id)
    if len(set(layer_ids)) != len(layer_ids):
        raise RuntimeError("повтор id слоя")
    seen = []
    pop_sum = 0
    for district in districts:
        if not isinstance(district, dict):
            raise RuntimeError("район не объект")
        district_id = district.get("id")
        if not isinstance(district_id, str) or not district_id:
            raise RuntimeError("пустой id района")
        if not isinstance(district.get("name"), str) or not district["name"]:
            raise RuntimeError(f"район {district_id} без имени")
        if not isinstance(district.get("type"), str) or not district["type"]:
            raise RuntimeError(f"район {district_id} без типа")
        pop_sum += _need_int(district, "pop_permille", district_id, 0)
        _need_int(district, "traffic", district_id, 0, 100)
        _need_int(district, "appeal_permille", district_id, 0)
        district["layers_permille"] = _shares(district.get("layers_permille"), layer_ids, district_id)
        seen.append(district_id)
    if len(set(seen)) != len(seen):
        raise RuntimeError("повтор id района")
    if pop_sum != 1000:
        raise RuntimeError("доли населения районов в сумме не 1000")
    return book


def allocate_population(population: int, districts: list[dict]) -> list[int]:
    if isinstance(population, bool) or not isinstance(population, int) or population < 0:
        raise RuntimeError("население города должно быть целым неотрицательным")
    return split_largest_remainder(
        population,
        [int(row["pop_permille"]) for row in districts],
        [str(row["id"]) for row in districts],
    )


def allocate_layers(population: int, layer_ids: list[str], shares: dict[str, int]) -> list[int]:
    if isinstance(population, bool) or not isinstance(population, int) or population < 0:
        raise RuntimeError("население района должно быть целым неотрицательным")
    return split_largest_remainder(
        population,
        [int(shares[layer_id]) for layer_id in layer_ids],
        list(layer_ids),
    )
