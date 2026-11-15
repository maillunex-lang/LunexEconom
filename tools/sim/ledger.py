"""Двойная запись. Сумма строк проводки всегда 0. Счёт игрока не уходит в минус."""
from __future__ import annotations


class Ledger:
    def __init__(self) -> None:
        self.balances: dict[str, int] = {
            "system:treasury": 0,
            "system:market": 0,
            "system:upkeep": 0,
        }
        self.entries: list[dict] = []
        self.seen: dict[str, int] = {}
        self.min_player: dict[str, int] = {}

    def balance(self, account: str) -> int:
        return self.balances.get(account, 0)

    def post(self, request_id: str, lines: list[tuple[str, int]]) -> int | None:
        if len(lines) < 2:
            raise RuntimeError(f"проводка {request_id} короче двух строк")
        total = 0
        for account, delta in lines:
            if not isinstance(delta, int) or isinstance(delta, bool):
                raise RuntimeError(f"не целая сумма в {request_id}")
            total += delta
        if total != 0:
            raise RuntimeError(f"проводка {request_id} не сходится: {total}")
        if request_id in self.seen:
            return self.seen[request_id]
        for account, delta in lines:
            if delta < 0 and account.startswith("player:"):
                if self.balances.get(account, 0) + delta < 0:
                    return None
        for account, delta in lines:
            self.balances[account] = self.balances.get(account, 0) + delta
            if account.startswith("player:"):
                cash = self.balances[account]
                if account not in self.min_player or cash < self.min_player[account]:
                    self.min_player[account] = cash
        self.seen[request_id] = len(self.entries)
        self.entries.append({"request_id": request_id, "lines": [[a, d] for a, d in lines]})
        return self.seen[request_id]

    def audit(self) -> None:
        if sum(self.balances.values()) != 0:
            raise RuntimeError(f"сумма счетов {sum(self.balances.values())}")
        for entry in self.entries:
            if sum(delta for _, delta in entry["lines"]) != 0:
                raise RuntimeError(f"кривая проводка {entry['request_id']}")
        for account, cash in self.balances.items():
            if account.startswith("player:") and cash < 0:
                raise RuntimeError(f"{account} ушёл в минус")
