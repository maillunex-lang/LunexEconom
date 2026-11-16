"""Стенд баланса: окупаемость каждого рецепта и здания по справочным ценам каталога (GDD 36).

Запуск: python -m tools.balance.bench [--catalog server/data] [--json out.json] [--goal-lo 15 --goal-hi 30]
Только целые числа, деление вниз. Чтение каталога, ничего не меняет.
Допущения: полная загрузка (staffing 100 %), все выходы продаются по справочной цене, входы покупаются по ней же,
зарплата за рабочее место в месяц берётся из параметра (по умолчанию 100 ₽ как в черновике), месяц = 30 суток.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

DAYS_MONTH = 30


def load(path):
    p = Path(path)
    return (json.loads((p / "products.json").read_text(encoding="utf-8")),
            json.loads((p / "buildings.json").read_text(encoding="utf-8")),
            json.loads((p / "recipes.json").read_text(encoding="utf-8")))


def analyse(products, buildings, recipes, wage_month=100):
    price = {x["id"]: x["reference_price"] for x in products}
    bld = {x["id"]: x for x in buildings}
    rows = []
    for r in recipes:
        b = bld.get(r["building"])
        if not b:
            continue
        out_value = sum(price.get(k, 0) * v for k, v in r["outputs"].items())
        in_value = sum(price.get(k, 0) * v for k, v in r["inputs"].items())
        added_day = out_value - in_value
        wages = b["jobs"] * wage_month
        profit_month = added_day * DAYS_MONTH - wages - b["upkeep_month"]
        payback_days = (b["build_cost"] * DAYS_MONTH // profit_month) if profit_month > 0 else None
        rows.append({
            "recipe": r["id"], "building": r["building"], "jobs": b["jobs"], "build_cost": b["build_cost"],
            "upkeep_month": b["upkeep_month"], "out_value_day": out_value, "in_value_day": in_value,
            "added_day": added_day, "profit_month": profit_month, "payback_days": payback_days,
            "margin_bp": (added_day * 10000 // out_value) if out_value else 0,
        })
    return rows


def classify(rows, goal_lo, goal_hi):
    """Метки: loss (убыток), slow (дольше цели), fast (быстрее цели), ok."""
    for r in rows:
        d = r["payback_days"]
        r["flag"] = "loss" if d is None else "fast" if d < goal_lo else "slow" if d > goal_hi * 12 else "ok"
    return rows


def render(rows):
    lines = ["рецепт | здание | вложение | прибыль/мес | окупаемость, суток | маржа bp | метка"]
    for r in sorted(rows, key=lambda x: (x["payback_days"] is None, -(x["payback_days"] or 0))):
        lines.append(f'{r["recipe"]} | {r["building"]} | {r["build_cost"]} | {r["profit_month"]} | '
                     f'{r["payback_days"] if r["payback_days"] is not None else "-"} | {r["margin_bp"]} | {r["flag"]}')
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="server/data")
    ap.add_argument("--json")
    ap.add_argument("--wage", type=int, default=100)
    ap.add_argument("--goal-lo", type=int, default=15)
    ap.add_argument("--goal-hi", type=int, default=30)
    a = ap.parse_args(argv)
    rows = classify(analyse(*load(a.catalog), wage_month=a.wage), a.goal_lo, a.goal_hi)
    print(render(rows))
    summary = {f: sum(1 for r in rows if r["flag"] == f) for f in ("ok", "loss", "slow", "fast")}
    print("\nИтого:", summary)
    if a.json:
        Path(a.json).write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
