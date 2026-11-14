"""City government: the mayor, tax policy within legal limits, social service coverage and the monthly city budget.

The budget is the wallet of the pseudo-owner economy.CITY (taxes flow in, see taxes.py). The mayor can change profit and
property tax (inside economy.PROFIT_TAX_LIMITS / PROPERTY_TAX_LIMITS, once per game month) and order social buildings
(school, hospital, park) that are paid from the budget. VAT is federal law and cannot be changed by the mayor.
Shared by SQLite and PostgreSQL (`ph` = SQL placeholder).
"""
import hashlib
import json
import math

import economy
import taxes

ADMIN = "npc:administration"
ADMIN_NAME = "Городская администрация"
DEFAULT_SOCIAL_SHARE = 0.30


def _q(sql, ph):
    return sql.replace("%s", ph)


def ensure(db, ph, month=0):
    """Create the default mayor (the administration) and the default policy once."""
    if db.execute("SELECT 1 FROM city_state WHERE id=1").fetchone() is None:
        db.execute(_q("INSERT INTO city_state(id,mayor,mayor_name,since_month,term_end_month) VALUES(1,%s,%s,%s,%s)", ph),
                   (ADMIN, ADMIN_NAME, month, month + economy.ELECTION_PERIOD))
    if db.execute("SELECT 1 FROM city_policy WHERE id=1").fetchone() is None:
        db.execute(_q("INSERT INTO city_policy(id,profit_tax_permille,property_tax_permille,social_share_permille,changed_month) VALUES(1,%s,%s,%s,%s)", ph),
                   (int(round(economy.DEFAULT_PROFIT_TAX * 1000)), int(round(economy.DEFAULT_PROPERTY_TAX * 1000)),
                    int(DEFAULT_SOCIAL_SHARE * 1000), -1))


def mayor(db, ph, month=0):
    ensure(db, ph, month)
    m, name, since, end = db.execute("SELECT mayor,mayor_name,since_month,term_end_month FROM city_state WHERE id=1").fetchone()
    return {"owner": m, "name": name, "since_month": int(since), "term_end_month": int(end), "is_npc": m.startswith("npc:")}


def is_mayor(db, ph, owner, month=0):
    return mayor(db, ph, month)["owner"] == owner


def set_mayor(db, ph, owner, name, month):
    ensure(db, ph, month)
    db.execute(_q("UPDATE city_state SET mayor=%s,mayor_name=%s,since_month=%s,term_end_month=%s WHERE id=1", ph),
               (owner, name, month, month + economy.ELECTION_PERIOD))


def set_taxes(db, ph, owner, profit, prop, month):
    """The mayor changes profit/property tax; limits are the law, at most one change per game month."""
    if not taxes.enabled():
        return 409, {"error": "taxes_disabled"}
    if not is_mayor(db, ph, owner, month):
        return 403, {"error": "not_mayor"}
    for value in (profit, prop):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return 400, {"error": "invalid_rate"}
    lo_p, hi_p = economy.PROFIT_TAX_LIMITS
    lo_i, hi_i = economy.PROPERTY_TAX_LIMITS
    if not (lo_p - 1e-9 <= profit <= hi_p + 1e-9 and lo_i - 1e-9 <= prop <= hi_i + 1e-9):
        return 400, {"error": "out_of_limits", "limits": {"profit_tax": [lo_p, hi_p], "property_tax": [lo_i, hi_i]}}
    changed = int(db.execute("SELECT changed_month FROM city_policy WHERE id=1").fetchone()[0])
    if changed >= month:
        return 409, {"error": "cooldown", "next_change_month": changed + 1}
    db.execute(_q("UPDATE city_policy SET profit_tax_permille=%s,property_tax_permille=%s,changed_month=%s WHERE id=1", ph),
               (int(round(profit * 1000)), int(round(prop * 1000)), month))
    return 200, {"ok": True, "taxes": taxes.view(db, ph)}


def social_counts(db, ph, month):
    counts = {k: 0 for k in economy.SOCIAL_KINDS}
    for kind, in db.execute(_q("SELECT kind FROM building_ops WHERE owner=%s AND start_month<=%s", ph), (economy.CITY, month)).fetchall():
        if kind in counts:
            counts[kind] += 1
    return counts


def social(db, ph, month, population, funded=True):
    """Coverage (0..1) of every service and the quality-of-life index."""
    counts = social_counts(db, ph, month)
    coverage = {}
    for kind in economy.SOCIAL_KINDS:
        served = counts[kind] * economy.PRODUCTION[kind]["serves"]
        coverage[kind] = min(1.0, served / max(population, 1)) * (1.0 if funded else 0.5)
    quality = sum(coverage.values()) / len(economy.SOCIAL_KINDS)
    return {"counts": counts, "coverage": coverage, "quality": quality, "funded": bool(funded)}


def monthly(db, ph, month, now):
    """City expenses outside company payroll: road maintenance and the human mayor's salary (never below zero)."""
    budget = economy.player_account(economy.CITY)
    cash = economy.balance(db, ph, economy.CITY) or 0
    m = mayor(db, ph, month)
    roads = db.execute("SELECT COUNT(*) FROM roads").fetchone()[0]
    road_cost = min(int(roads) * economy.ROAD_MAINTENANCE, max(cash, 0))
    if road_cost:
        economy.post(db, ph, "city", "Содержание дорог: %d" % road_cost, [(budget, -road_cost), (economy.UPKEEP, road_cost)], now)
        cash -= road_cost
    if not m["is_npc"]:
        salary = min(economy.MAYOR_SALARY, max(cash, 0))
        if salary:
            economy.ensure_wallet(db, ph, m["owner"], now)
            economy.post(db, ph, "city", "Зарплата мэра: %d" % salary, [(budget, -salary), (economy.player_account(m["owner"]), salary)], now)


# ---------------------------------------------------------------- elections
# Term of `economy.ELECTION_PERIOD` months ending at `term_end_month` E. Registration: the two months before voting,
# voting: months E-2 and E-1, the result is counted when month E-1 completes and the winner governs from month E.
NPC_CANDIDATES = [
    {"owner": "npc:growth-party", "name": "Партия роста", "profit": 0.08, "property": 0.010, "social": 0.20,
     "slogan": "Низкие налоги — больше предприятий"},
    {"owner": "npc:social-course", "name": "Социальный курс", "profit": 0.18, "property": 0.022, "social": 0.60,
     "slogan": "Школы, больницы, парки"},
]


def phase(month, term_end):
    vote_start = term_end - economy.ELECTION_VOTING_MONTHS
    reg_start = vote_start - economy.ELECTION_REGISTRATION_MONTHS
    if reg_start <= month < vote_start:
        return "registration"
    if vote_start <= month < term_end:
        return "voting"
    return "idle"


def _permille(value):
    return int(round(value * 1000))


def _candidate_row(row):
    owner, name, profit, prop, social, slogan = row
    return {"owner": owner, "name": name, "profit_tax": profit / 1000.0, "property_tax": prop / 1000.0,
            "social_share": social / 1000.0, "slogan": slogan, "is_npc": owner.startswith("npc:")}


def candidates(db, ph, election):
    rows = db.execute(_q("SELECT candidate,name,profit_permille,property_permille,social_permille,slogan FROM election_candidates "
                         "WHERE election=%s ORDER BY candidate", ph), (election,)).fetchall()
    return [_candidate_row(r) for r in rows]


def _add_candidate(db, ph, election, owner, name, profit, prop, social, slogan):
    db.execute(_q("INSERT INTO election_candidates(election,candidate,name,profit_permille,property_permille,social_permille,slogan) "
                  "VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(election,candidate) DO NOTHING", ph),
               (election, owner, name, _permille(profit), _permille(prop), _permille(social), slogan))


def ensure_candidates(db, ph, month):
    """Register the NPC candidates (and an NPC incumbent) once the registration period starts."""
    m = mayor(db, ph, month)
    if phase(month, m["term_end_month"]) == "idle":
        return
    election = m["term_end_month"]
    for c in NPC_CANDIDATES:
        _add_candidate(db, ph, election, c["owner"], c["name"], c["profit"], c["property"], c["social"], c["slogan"])
    if m["is_npc"]:
        row = db.execute("SELECT profit_tax_permille,property_tax_permille,social_share_permille FROM city_policy WHERE id=1").fetchone()
        _add_candidate(db, ph, election, m["owner"], m["name"], row[0] / 1000.0, row[1] / 1000.0, row[2] / 1000.0, "Стабильность и преемственность")


def jobs_of(db, ph, owner):
    return sum(economy.PRODUCTION[k]["jobs"] for k, in db.execute(_q("SELECT kind FROM building_ops WHERE owner=%s", ph), (owner,)).fetchall()
               if k in economy.PRODUCTION)


def vote_weight(db, ph, owner):
    return economy.VOTE_WEIGHT_BASE + economy.VOTE_WEIGHT_PER_JOB * jobs_of(db, ph, owner)


def register_candidate(db, ph, owner, profit, prop, slogan, month, now):
    m = mayor(db, ph, month)
    if phase(month, m["term_end_month"]) != "registration":
        return 409, {"error": "not_registration_period"}
    if owner.startswith("npc:") or owner == economy.CITY:
        return 403, {"error": "not_allowed"}
    for value in (profit, prop):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return 400, {"error": "invalid_rate"}
    lo_p, hi_p = economy.PROFIT_TAX_LIMITS
    lo_i, hi_i = economy.PROPERTY_TAX_LIMITS
    if not (lo_p - 1e-9 <= profit <= hi_p + 1e-9 and lo_i - 1e-9 <= prop <= hi_i + 1e-9):
        return 400, {"error": "out_of_limits", "limits": {"profit_tax": [lo_p, hi_p], "property_tax": [lo_i, hi_i]}}
    slogan = str(slogan or "").strip()[:80]
    election = m["term_end_month"]
    if jobs_of(db, ph, owner) <= 0:
        return 403, {"error": "no_company"}
    if db.execute(_q("SELECT 1 FROM election_candidates WHERE election=%s AND candidate=%s", ph), (election, owner)).fetchone():
        return 409, {"error": "already_registered"}
    economy.ensure_wallet(db, ph, owner, now)
    if (economy.balance(db, ph, owner) or 0) < economy.ELECTION_FEE:
        return 402, {"error": "insufficient_funds", "fee": economy.ELECTION_FEE}
    economy.post(db, ph, "city", "Взнос кандидата в мэры", [(economy.player_account(owner), -economy.ELECTION_FEE), (economy.player_account(economy.CITY), economy.ELECTION_FEE)], now)
    _add_candidate(db, ph, election, owner, owner, profit, prop, DEFAULT_SOCIAL_SHARE, slogan or "Мой город — моя программа")
    return 201, {"ok": True, "election": election, "balance": economy.balance(db, ph, owner)}


def cast_vote(db, ph, owner, candidate, month):
    m = mayor(db, ph, month)
    if phase(month, m["term_end_month"]) != "voting":
        return 409, {"error": "not_voting_period"}
    if owner.startswith("npc:") or owner == economy.CITY:
        return 403, {"error": "not_allowed"}
    election = m["term_end_month"]
    ensure_candidates(db, ph, month)
    if not db.execute(_q("SELECT 1 FROM election_candidates WHERE election=%s AND candidate=%s", ph), (election, str(candidate))).fetchone():
        return 404, {"error": "unknown_candidate"}
    if jobs_of(db, ph, owner) <= 0:
        return 403, {"error": "no_company"}          # only people running a business in the city vote as players
    db.execute(_q("INSERT INTO election_votes(election,voter,candidate) VALUES(%s,%s,%s) ON CONFLICT(election,voter) DO UPDATE SET candidate=excluded.candidate", ph),
               (election, owner, str(candidate)))
    return 200, {"ok": True, "candidate": str(candidate), "weight": vote_weight(db, ph, owner)}


def _noise(election, candidate):
    digest = hashlib.sha256(("%d|%s|residents" % (election, candidate)).encode()).digest()
    return (int.from_bytes(digest[:4], "big") / 0xFFFFFFFF - 0.5) * 0.2          # +-0.1, deterministic


def resident_shares(cands, incumbent, unemployment, quality, election):
    """Share of the residents' votes for each candidate (softmax of a simple utility).

    Residents like social spending, like low profit tax when jobs are scarce (unemployment) and reward an incumbent
    for a good quality of life."""
    scores = {}
    for c in cands:
        u = 1.2 * c["social_share"] + 0.8 * unemployment * (1.0 - c["profit_tax"] / economy.PROFIT_TAX_LIMITS[1])
        if c["owner"] == incumbent:
            u += 0.3 * quality
        scores[c["owner"]] = u + _noise(election, c["owner"])
    top = max(scores.values())
    weights = {k: math.exp(3.0 * (v - top)) for k, v in scores.items()}
    total = sum(weights.values())
    return {k: v / total for k, v in weights.items()}


def last_result(db, ph):
    row = db.execute("SELECT election,winner,winner_name,tally,month_index FROM election_results ORDER BY election DESC LIMIT 1").fetchone()
    if not row:
        return None
    return {"election": int(row[0]), "winner": row[1], "winner_name": row[2], "tally": json.loads(row[3]), "month_index": int(row[4])}


def tally_if_due(db, ph, month, population, unemployment, quality, now):
    """Count the votes when the last voting month completes; the winner takes office and promises become policy."""
    m = mayor(db, ph, month)
    election = m["term_end_month"]
    if month != election - 1:
        return None
    ensure_candidates(db, ph, month)
    cands = candidates(db, ph, election)
    if not cands:
        set_mayor(db, ph, m["owner"], m["name"], election)             # nobody ran: the incumbent stays for another term
        return None
    shares = resident_shares(cands, m["owner"], unemployment, quality, election)
    votes = {c["owner"]: shares[c["owner"]] * population for c in cands}
    player_votes = {c["owner"]: 0 for c in cands}
    for voter, candidate in db.execute(_q("SELECT voter,candidate FROM election_votes WHERE election=%s ORDER BY voter", ph), (election,)).fetchall():
        w = vote_weight(db, ph, voter)
        votes[candidate] += w
        player_votes[candidate] += w
    order = sorted(cands, key=lambda c: (-round(votes[c["owner"]], 6), c["owner"] != m["owner"], c["owner"]))      # ties: incumbent first
    winner = order[0]
    tally = [{"owner": c["owner"], "name": c["name"], "votes": int(round(votes[c["owner"]])), "player_votes": int(player_votes[c["owner"]]),
              "resident_share": round(shares[c["owner"]], 3)} for c in order]
    db.execute(_q("INSERT INTO election_results(election,winner,winner_name,tally,month_index) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(election) DO NOTHING", ph),
               (election, winner["owner"], winner["name"], json.dumps(tally, ensure_ascii=False), month))
    set_mayor(db, ph, winner["owner"], winner["name"], election)
    db.execute(_q("UPDATE city_policy SET profit_tax_permille=%s,property_tax_permille=%s,social_share_permille=%s,changed_month=%s WHERE id=1", ph),
               (_permille(winner["profit_tax"]), _permille(winner["property_tax"]), _permille(winner["social_share"]), election - 1))
    return winner["owner"]


def election_view(db, ph, month, owner=None):
    m = mayor(db, ph, month)
    election = m["term_end_month"]
    ph_name = phase(month, election)
    if ph_name != "idle":
        ensure_candidates(db, ph, month)
    cands = candidates(db, ph, election)
    my_vote = None
    if owner:
        row = db.execute(_q("SELECT candidate FROM election_votes WHERE election=%s AND voter=%s", ph), (election, owner)).fetchone()
        my_vote = row[0] if row else None
    registered = any(c["owner"] == owner for c in cands) if owner else False
    return {"phase": ph_name, "election_month": election, "fee": economy.ELECTION_FEE,
            "registration_start": election - economy.ELECTION_VOTING_MONTHS - economy.ELECTION_REGISTRATION_MONTHS,
            "voting_start": election - economy.ELECTION_VOTING_MONTHS, "candidates": cands, "my_vote": my_vote, "registered": registered,
            "can_register": bool(owner) and ph_name == "registration" and not registered and not owner.startswith("npc:") and jobs_of(db, ph, owner) > 0,
            "can_vote": bool(owner) and ph_name == "voting" and jobs_of(db, ph, owner) > 0,
            "vote_weight": vote_weight(db, ph, owner) if owner else 0, "last_result": last_result(db, ph)}
