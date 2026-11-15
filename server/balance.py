"""Tunable balance registry (EX-02, docs/BALANCE_REGISTRY.md).

Defaults are the numbers the live game already uses. ``economy`` reads them once
at import and keeps the same names. Override a run with ``LUNEX_BALANCE_FILE``
(JSON object) or ``LUNEX_BAL_<NAME>`` in the environment, set before the process
imports ``economy``. ``reload()`` updates this registry only; already-imported
``economy`` constants stay until the process restarts.
"""
import json
import os

# name -> default. Bool and int are not interchangeable (NPC_NEW_KINDS is 0/1).
DEFAULTS = {
    # labour
    "BASE_WAGE": 1_500,
    "PARTICIPATION": 0.5,
    "BASE_POPULATION": 200,
    "MIN_POPULATION": 140,
    "WAGE_ELASTICITY": 0.8,
    "WAGE_MAX": 2.0,
    "INCOME_WEIGHT": 0.25,
    "INCOME_CAP": 1.5,
    # migration
    "NATURAL_GROWTH": 0.003,
    "MIGRATION_IN": 0.03,
    "MIGRATION_OUT": 0.005,
    "SOCIAL_GROWTH": 0.002,
    # taxes
    "TAXES_ENABLED": True,
    "VAT_STANDARD": 0.22,
    "DEFAULT_PROFIT_TAX": 0.13,
    "PROFIT_TAX_MIN": 0.05,
    "PROFIT_TAX_MAX": 0.25,
    "DEFAULT_PROPERTY_TAX": 0.022,
    "PROPERTY_TAX_MIN": 0.0,
    "PROPERTY_TAX_MAX": 0.022,
    # credit
    "LOAN_INTEREST": 0.015,
    "LOAN_LTV": 0.5,
    "LOAN_MAX": 5_000_000,
    "LOAN_MIN": 10_000,
    "LOAN_NEW_LTV": 0.12,
    "LOAN_RAMP_MONTHS": 12,
    "LOAN_REVENUE_MONTHS": 3,
    "LOAN_REVENUE_PROOF": 20_000,
    "BANKRUPT_AFTER_MISSED": 3,
    "DISTRESS_OUTPUT": 0.5,
    "LIQUIDATION_RATE": 0.4,
    "SELL_RATE": 0.5,
    "INVENTORY_LIQUIDATION_RATE": 0.5,
    "NPC_RECAPITAL_MONTHS": 6,
    # retail and owner spending
    "RETAIL_ENABLED": True,
    "RETAIL_MARKUP": 0.30,
    "RESIDENT_SPEND_TO_MARKET": True,
    "OWNER_SPEND_ENABLED": True,
    "OWNER_SPEND_SHARE": 0.35,
    "OWNER_SPEND_RESERVE_MONTHS": 3,
    "HOLD_BELOW": 0.9,
    "HOLD_DEPTH": 0.5,
    "HOLD_SMOOTH_MONTHS": 3,
    "RELEASE_SHARE": 0.34,
    "MIN_PRICE_K": 0.25,
    "MAX_PRICE_K": 2.5,
    # construction (legacy building prices; new kinds stay in goods_catalog)
    "START_CAPITAL": 1_000_000,
    "ROAD_CELL_COST": 5_000,
    "WAREHOUSE_COST": 80_000,
    "SHOP_COST": 160_000,
    "SCHOOL_COST": 400_000,
    "HOSPITAL_COST": 800_000,
    "PARK_COST": 150_000,
    # city government (kept here so one file lists them; economy re-exports)
    "SOCIAL_PRODUCTIVITY": 0.10,
    "MAYOR_SALARY": 40_000,
    "MAYOR_BONUS_SHARE": 0.02,
    "TERM_BONUS_HIGH_RATING": 0.75,
    "TERM_BONUS_HIGH": 600_000,
    "TERM_BONUS_MID_RATING": 0.60,
    "TERM_BONUS_MID": 300_000,
    "RATING_RESIDENTS_WEIGHT": 0.7,
    "RATING_SMOOTHING": 0.2,
    "DISMISS_BELOW": 0.15,
    "DISMISS_AFTER": 3,
    "MAX_CONSECUTIVE_TERMS": 2,
    "ROAD_MAINTENANCE": 30,
    "ELECTION_PERIOD": 12,
    "ELECTION_REGISTRATION_MONTHS": 2,
    "ELECTION_VOTING_MONTHS": 2,
    "ELECTION_FEE": 50_000,
    "VOTE_WEIGHT_BASE": 10,
    "VOTE_WEIGHT_PER_JOB": 5,
    "CONTRACT_PRICE_MIN_K": 0.50,
    "CONTRACT_PRICE_MAX_K": 2.00,
    "CONTRACT_QTY_MIN": 1,
    "CONTRACT_QTY_MAX": 10_000,
    "CONTRACT_TERM_MIN": 1,
    "CONTRACT_TERM_MAX": 24,
    "CONTRACT_MAX_ACTIVE": 6,
    "CONTRACT_MAX_OPEN": 6,
    # transport. regions.py still owns SPEED_KMH and TRANSPORT_COST_PER_KM (that file is not edited here).
    # These copies are the registry view; trucks.py reads the TRUCK_* keys.
    "SPEED_KMH": 85,
    "TRANSPORT_COST_PER_KM": 0.0006,
    "TRUCK_CAPACITY": 40,
    "TRUCK_PRICE": 80_000,
    "TRUCK_UPKEEP": 2_000,
    "TRUCK_COST_PER_KM": 8,
    # zones. zoning.py does not import this registry (that file is owned elsewhere). Mirrors only.
    "ZONE_CORE_SHARE": 0.40,
    "ZONE_WEDGE_DEGREES": 100.0,
    "ZONE_EXPAND_FILL": 0.40,
    "ZONE_EXPAND_STEP": 0.25,
    "ZONE_MAX_LEVEL": 6,
    # product grade 1..5. Step is the price change per grade away from 3 (neutral).
    "QUALITY_PRICE_STEP": 0.05,
    "RESEARCH_COST": 80_000,
    "RESEARCH_MONTHS": 2,
    "RESEARCH_INPUT_RELIEF_PERMILLE": 100,
    # 0: NPCs keep the old kind list. 1: they also consider catalog producers (docs/INDUSTRIES.md).
    "NPC_NEW_KINDS": 0,
    # EX-05. Household headcount is real city population / POPULATION_SCALE.
    # HOUSEHOLDS_ENABLED stays off so labour, demand and the simulator digest do not move.
    "POPULATION_SCALE": 100,
    "HOUSEHOLDS_ENABLED": False,
    "BIRTHS_PER_1000": 12,
    "DEATHS_PER_1000": 10,
    "HH_CHILD_SHARE": 0.18,
    "HH_RETIRED_SHARE": 0.22,
    "HH_PARTICIPATION_PPM": 780,
    "HH_SAVINGS_PPM": 120,
    "HH_MIGRATION_PPM": 4,
    "HH_DEMAND_NUDGE_PPM": 20,
    "HH_SKILL_PPM": 1000,
    "HH_HOUSING_STRESS": 0,
    "HH_RECESSION": 0,
    "HOUSE_LEGACY_CAPACITY": 4,
    "FAMILY_PER_1000": 385,
    "MORTGAGE_TERM_MONTHS": 240,
    "MORTGAGE_RATE_YEAR": 0.12,
    "MORTGAGE_LTV_PPM": 700,
    "MORTGAGE_BURDEN_MAX_PPM": 450,
    "MORTGAGE_RATE_MIN_YEAR": 0.05,
    "MORTGAGE_RATE_MAX_YEAR": 0.40,
    # EX-09. Legacy revolving credit stays in bank.py / the loans table.
    "BANKS_ENABLED": False,
    "BANK_BASE_RATE_YEAR": 0.12,
    "BANK_RATE_MIN_YEAR": 0.05,
    "BANK_RATE_MAX_YEAR": 0.40,
    "BANK_RISK_STEP": 0.02,
    "BANK_MISSED_WARN": 1,
    "BANK_MISSED_RESTRUCTURE": 2,
    "BANK_MISSED_FORECLOSE": 4,
    "EQUIPMENT_COLLATERAL": 40_000,
    "CREDIT_BOOM": 0,
    "DIVIDEND_PAYOUT_PPM": 100,
    "DIVIDEND_MIN_CASH": 100_000,
    "INFLATION_ENABLED": False,
    "INFLATION_MIN_YEAR": 0.0,
    "INFLATION_MAX_YEAR": 0.10,
    "INFLATION_PRICE_WEIGHT": 0.85,
    "INFLATION_MONEY_WEIGHT": 0.15,
    "INFLATION_SHOCK": 0,
    # Profit, VAT and property are already collected by taxes.py. These three post only behind the flag.
    "TAX_EXTRAS_ENABLED": False,
    "LAND_TAX": 0.003,
    "PAYROLL_TAX": 0.15,
    "SECTOR_FEE": 0.01,
}

GROUPS = {
    "labour": ("BASE_WAGE", "PARTICIPATION", "BASE_POPULATION", "MIN_POPULATION", "WAGE_ELASTICITY", "WAGE_MAX", "INCOME_WEIGHT", "INCOME_CAP"),
    "migration": ("NATURAL_GROWTH", "MIGRATION_IN", "MIGRATION_OUT", "SOCIAL_GROWTH"),
    "taxes": ("TAXES_ENABLED", "VAT_STANDARD", "DEFAULT_PROFIT_TAX", "PROFIT_TAX_MIN", "PROFIT_TAX_MAX", "DEFAULT_PROPERTY_TAX", "PROPERTY_TAX_MIN", "PROPERTY_TAX_MAX", "TAX_EXTRAS_ENABLED", "LAND_TAX", "PAYROLL_TAX", "SECTOR_FEE"),
    "credit": ("LOAN_INTEREST", "LOAN_LTV", "LOAN_MAX", "LOAN_MIN", "LOAN_NEW_LTV", "LOAN_RAMP_MONTHS", "LOAN_REVENUE_MONTHS", "LOAN_REVENUE_PROOF", "BANKRUPT_AFTER_MISSED", "DISTRESS_OUTPUT", "LIQUIDATION_RATE", "SELL_RATE", "INVENTORY_LIQUIDATION_RATE", "NPC_RECAPITAL_MONTHS"),
    "retail": ("RETAIL_ENABLED", "RETAIL_MARKUP", "RESIDENT_SPEND_TO_MARKET", "HOLD_BELOW", "HOLD_DEPTH", "HOLD_SMOOTH_MONTHS", "RELEASE_SHARE", "MIN_PRICE_K", "MAX_PRICE_K"),
    "owner_spend": ("OWNER_SPEND_ENABLED", "OWNER_SPEND_SHARE", "OWNER_SPEND_RESERVE_MONTHS"),
    "construction": ("START_CAPITAL", "ROAD_CELL_COST", "WAREHOUSE_COST", "SHOP_COST", "SCHOOL_COST", "HOSPITAL_COST", "PARK_COST"),
    "transport": ("SPEED_KMH", "TRANSPORT_COST_PER_KM", "TRUCK_CAPACITY", "TRUCK_PRICE", "TRUCK_UPKEEP", "TRUCK_COST_PER_KM"),
    "zones": ("ZONE_CORE_SHARE", "ZONE_WEDGE_DEGREES", "ZONE_EXPAND_FILL", "ZONE_EXPAND_STEP", "ZONE_MAX_LEVEL"),
    "quality": ("QUALITY_PRICE_STEP", "RESEARCH_COST", "RESEARCH_MONTHS", "RESEARCH_INPUT_RELIEF_PERMILLE", "NPC_NEW_KINDS"),
    "population": ("POPULATION_SCALE", "HOUSEHOLDS_ENABLED", "BIRTHS_PER_1000", "DEATHS_PER_1000", "HH_CHILD_SHARE", "HH_RETIRED_SHARE", "HH_PARTICIPATION_PPM", "HH_SAVINGS_PPM", "HH_MIGRATION_PPM", "HH_DEMAND_NUDGE_PPM", "HH_SKILL_PPM", "HH_HOUSING_STRESS", "HH_RECESSION", "HOUSE_LEGACY_CAPACITY", "FAMILY_PER_1000"),
    "housing": ("MORTGAGE_TERM_MONTHS", "MORTGAGE_RATE_YEAR", "MORTGAGE_LTV_PPM", "MORTGAGE_BURDEN_MAX_PPM", "MORTGAGE_RATE_MIN_YEAR", "MORTGAGE_RATE_MAX_YEAR"),
    "banks": ("BANKS_ENABLED", "BANK_BASE_RATE_YEAR", "BANK_RATE_MIN_YEAR", "BANK_RATE_MAX_YEAR", "BANK_RISK_STEP", "BANK_MISSED_WARN", "BANK_MISSED_RESTRUCTURE", "BANK_MISSED_FORECLOSE", "EQUIPMENT_COLLATERAL", "CREDIT_BOOM", "DIVIDEND_PAYOUT_PPM", "DIVIDEND_MIN_CASH"),
    "inflation": ("INFLATION_ENABLED", "INFLATION_MIN_YEAR", "INFLATION_MAX_YEAR", "INFLATION_PRICE_WEIGHT", "INFLATION_MONEY_WEIGHT", "INFLATION_SHOCK"),
}


def _coerce(default, raw):
    if isinstance(default, bool):
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, int) and not isinstance(default, bool):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    return raw


def load():
    values = dict(DEFAULTS)
    path = os.environ.get("LUNEX_BALANCE_FILE")
    if path:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("balance file must be a JSON object")
        for key, raw in data.items():
            if key in values:
                values[key] = _coerce(values[key], raw)
    for key, default in DEFAULTS.items():
        raw = os.environ.get("LUNEX_BAL_" + key)
        if raw is not None and raw != "":
            values[key] = _coerce(default, raw)
    return values


PARAMS = load()


def get(name):
    # Runtime settings are read only through a processing context created by
    # production.step_month. Without one, preserve the original registry.
    import runtime_config
    return runtime_config.get(name, PARAMS[name])


def reload():
    """Re-read the environment and the file. Does not touch modules that already copied a value."""
    global PARAMS
    PARAMS = load()
    return PARAMS


def public_view():
    return {group: {key: PARAMS[key] for key in keys} for group, keys in GROUPS.items()}
