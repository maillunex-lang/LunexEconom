"""Новый эксперимент спроса плюс обратная совместимость с tools/sim/demand.py.

Папка нужна для нового дизайна, но старый M1/M2 импортирует tools.sim.demand:
загружаем неизменённый родительский модуль под отдельным именем.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_original_path = Path(__file__).resolve().parents[1] / "demand.py"
_spec = importlib.util.spec_from_file_location("tools.sim._legacy_demand", _original_path)
if _spec is None or _spec.loader is None:
    raise ImportError("Не найден старый симулятор спроса M1/M2")
_legacy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_legacy)
for _key in dir(_legacy):
    if not _key.startswith("_"):
        globals()[_key] = getattr(_legacy, _key)

from .model import run, rebuild_golden, load_inputs, migrate_shares
