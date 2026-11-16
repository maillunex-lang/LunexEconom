"""Командная строка эталонного симулятора M1."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.sim.catalog import repo_root
from tools.sim.engine import load_scenario, render_table, simulate
from tools.sim.balance import render as render_balance
from tools.sim.reach import simulate_reach


def _write(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def scenarios_dir() -> Path:
    return repo_root().joinpath("tools", "sim", "scenarios")


def golden_dir() -> Path:
    return repo_root().joinpath("tools", "sim", "golden")


def rebuild_golden() -> list[Path]:
    written = []
    all_scenarios = list(scenarios_dir().glob("*.json")) + list(scenarios_dir().joinpath("reach").glob("*.json"))
    for path in sorted(all_scenarios):
        scenario = load_scenario(path)
        is_reach = scenario.get("reach_enabled", False)
        report = simulate_reach(scenario) if is_reach else simulate(scenario)
        target = golden_dir().joinpath("reach", path.stem + ".json") if is_reach else golden_dir().joinpath(path.stem + ".json")
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
    if scenario.get("reach_enabled", False):
        report = simulate_reach(scenario, days=args.days)
        sys.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    else:
        report = simulate(scenario, days=args.days)
        sys.stdout.write(render_table(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
