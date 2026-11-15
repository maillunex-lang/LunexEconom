"""Чтение каталога из server/data/*.json. Числа в код не копируются."""
from __future__ import annotations

import json
from pathlib import Path


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.joinpath("server", "data", "products.json").is_file():
            return parent
    raise RuntimeError("не найден корень репозитория с server/data/products.json")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class Catalog:
    def __init__(self, root: Path | None = None):
        self.root = root or repo_root()
        data = self.root.joinpath("server", "data")
        self.products = {row["id"]: row for row in _load(data.joinpath("products.json"))}
        self.buildings = {row["id"]: row for row in _load(data.joinpath("buildings.json"))}
        self.recipes = {row["id"]: row for row in _load(data.joinpath("recipes.json"))}
        self.cities = {row["id"]: row for row in _load(data.joinpath("cities.json"))["cities"]}

    def recipe_for(self, recipe_id: str) -> dict:
        try:
            return self.recipes[recipe_id]
        except KeyError as exc:
            raise RuntimeError(f"неизвестный рецепт {recipe_id}") from exc

    def building(self, building_id: str) -> dict:
        try:
            return self.buildings[building_id]
        except KeyError as exc:
            raise RuntimeError(f"неизвестное здание {building_id}") from exc

    def product(self, product_id: str) -> dict:
        try:
            return self.products[product_id]
        except KeyError as exc:
            raise RuntimeError(f"неизвестный товар {product_id}") from exc

    def city(self, city_id: str) -> dict:
        try:
            return self.cities[city_id]
        except KeyError as exc:
            raise RuntimeError(f"неизвестный город {city_id}") from exc


def read_flag(name: str, root: Path | None = None) -> int:
    """Целое значение флага из server/enterprises/__init__.py, без копии числа."""
    base = root or repo_root()
    text = base.joinpath("server", "enterprises", "__init__.py").read_text(encoding="utf-8")
    pos = text.find(name)
    if pos < 0:
        raise RuntimeError(f"флаг {name} не найден")
    digits: list[str] = []
    seen = False
    for ch in text[pos:]:
        if ch.isdigit():
            digits.append(ch)
            seen = True
        elif seen:
            break
    if not digits:
        raise RuntimeError(f"у флага {name} нет целого значения")
    return int("".join(digits))


def salary_worker_draft(root: Path | None = None) -> int:
    return read_flag("enterprise_salary_worker_draft", root)
