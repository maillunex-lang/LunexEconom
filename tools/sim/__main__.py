"""Командная строка эталонного симулятора M1."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.sim.catalog import repo_root
from tools.sim.engine import load_scenario, render_table, simulate
from tools.sim.balance import render as render_balance


def _write(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def scenarios_dir() -> Path:
    return repo_root().joinpath("tools", "sim", "scenarios")


def golden_dir() -> Path:
    return repo_root().joinpath("tools", "sim", "golden")


def rebuild_golden() -> list[Path]:
    written = []
    for path in sorted(scenarios_dir().glob("*.json")):
        report = simulate(load_scenario(path))
        target = golden_dir().joinpath(path.stem + ".json")
        _write(target, report)
        written.append(target)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.sim")
    parser.add_argument("command", choices=("run", "golden", "balance"))
    parser.add_argument("scenario", nargs="?")
    parser.add_argument("--days", type=int)
    args = parser.parse_args(argv)
    if args.command == "balance":
        if args.scenario is not None or args.days is not None:
            print("balance не принимает сценарий и --days: сетка задана в tools/sim/balance.py", file=sys.stderr)
            return 2
        sys.stdout.write(render_balance())
        return 0
    if args.command == "golden":
        if args.scenario is not None or args.days is not None:
            print("golden не принимает сценарий и --days: он пересобирает все сценарии", file=sys.stderr)
            return 2
        for path in rebuild_golden():
            print(path)
        return 0
    if args.scenario is None:
        print("нужен путь к сценарию", file=sys.stderr)
        return 2
    scenario = load_scenario(Path(args.scenario))
    report = simulate(scenario, days=args.days)
    sys.stdout.write(render_table(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
