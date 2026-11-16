"""Сборка страницы «Доска задач» из docs/work_plan.json (шаблон template.html).

python tools/work_board/build.py out.html   — собрать файл для публикации как Artifact (db: состояние задач).
Доску публикует директор; состояние задач (выдано, сдано, принято) хранится в общей базе страницы (коллекция tasks).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import work_plan  # noqa: E402

SELFCHECK = {
    "A": ["Полный набор server/tests проходит на изолированной PostgreSQL 16 (приложен результат)",
          "Новые флаги по умолчанию выключены, при выключенном поведение прежнее",
          "Деньги только через ledger, идемпотентность по request_id, нет отрицательных остатков",
          "Менялись только файлы своей зоны, общие файлы директора не тронуты",
          "Есть docs/qa/<id>.md с разделом «Допущения»"],
    "B": ["Все проверки из client-check.yml прошли локально на Godot 4.7.2 (с таймаутом, результат приложен)",
          "Строки только в docs/content/ui_strings.ru.md, python tools/build_strings.py --check проходит",
          "Нет сырых ключей, ничего не обрезается на 16:9 и 20:9, кнопки не меньше 48 dp",
          "Новый smoke-тест подключён в client-check.yml и работает на моках",
          "Есть docs/qa/<id>.md с разделом «Допущения»"],
}
ACCEPT = ["Пробное слияние с актуальным main без конфликтов",
          "Список изменённых файлов только в зоне линии",
          "Полные тесты у директора: серверные на PostgreSQL 16 или все клиентские на Godot",
          "CI на PR зелёный, найденные дефекты исправлены до слияния",
          "Слияние squash в main выполняет директор; затем пакет принимается кнопкой «Принято, в архив»"]


def build(out, plan_file=None):
    if plan_file:
        work_plan.PLAN = Path(plan_file).resolve()
    plan = work_plan.load()
    data = {"lanes": plan["lanes"], "selfcheck": SELFCHECK, "acceptance": ACCEPT, "packages": []}
    for p in plan["packages"]:
        data["packages"].append({k: p[k] for k in ("id", "title", "lane", "step", "depends_on", "goal")} | {"prompt": work_plan.prompt(plan, p["id"])})
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = (Path(__file__).with_name("template.html")).read_text(encoding="utf-8").replace("/*PLAN_JSON*/", blob)
    Path(out).write_text(html, encoding="utf-8")


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "work_board.html", sys.argv[2] if len(sys.argv) > 2 else None)
    print("готово")
