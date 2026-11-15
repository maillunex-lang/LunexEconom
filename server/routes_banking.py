"""Bank, share and inflation routes (EX-09). Documented in docs/BANKING.md.

POST handlers match `_player_command`: fn(db, ph, owner, payload, now, month). Idempotent on request_id.
"""
import banking
import inflation


def handle_get(db, ph, path, query, owner):
    if path == "/bank/offers":
        return 200, banking.offers(db, ph, owner)
    if path == "/inflation":
        return 200, inflation.view(db, ph)
    if path == "/bank/loans":
        if not owner:
            return 401, {"error": "unauthorized"}
        return 200, banking.loans_of(db, ph, owner)
    return 404, {"error": "not_found"}


def loan(db, ph, owner, payload, now, month):
    return banking.loan(db, ph, owner, payload, now, month)


def repay(db, ph, owner, payload, now, month):
    return banking.repay(db, ph, owner, payload, now, month)


def buy_shares(db, ph, owner, payload, now, month):
    return banking.buy_shares(db, ph, owner, payload, now, month)
