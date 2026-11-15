"""Real-world price calibration of the city objects, different in every city of Bashkortostan (docs/REGIONAL_PRICES.md).

The game keeps its own currency. The conversion to real roubles is ONE constant, REAL_PER_GAME: the average wage of the republic (about
74 400 real roubles a month in 2025) is paid in the game as BASE_WAGE (1 500 game roubles), so 1 game rouble is worth 50 real ones (74 400 / 1 500 =
49.6, rounded). Every real-world figure below is therefore divided by 50 to get game roubles.

Per-city differences come from indices relative to Ufa, computed from the city's population (server/geo.py) with an optional override table for
official statistics: where Bashkortostanstat, a developer or a market study gives a number for a city, put it into OVERRIDES and the formula is
bypassed. Everything marked ESTIMATE is a modelling assumption, not a statistic; sources of the anchor numbers are in the documentation.
"""
import geo

REAL_PER_GAME = 50                    # 1 game rouble = 50 real roubles (calibrated on the average wage)
AREA_PER_RESIDENT = 30                # total floor area per resident in housing, m2 (RF average is about 27-30)

# Ufa anchors, real roubles per m2 (2025). Sources: new-build price 160-172 thousand (Mir kvartir, Yandex Realty); build cost: Bashkortostanstat
# 2022 average 63 thousand per m2 of delivered housing and 99 thousand for mass apartment blocks in Kazan in January 2025 (Union of cost
# engineers); the values per structure type are ESTIMATE between those anchors.
MARKET_PRICE_M2_UFA = 171_000         # new-build sale price
RENT_M2_MONTH_UFA = 550               # ESTIMATE, rent per m2 per month
BUILD_COST_M2_UFA = {                 # ESTIMATE
    "wood": 70_000, "light": 80_000, "brick": 90_000, "panel": 95_000, "monolith": 115_000, "public": 130_000, "ground": 12_000,
}

# City types adjust the wage index (mining and chemical towns pay more than agricultural ones).
WAGE_BONUS_WORDS = ("нефть", "нефтехимия", "химия", "добыча", "горнодобыча", "металлургия", "энергетика")

# Override table: {city_id: {"construction": x, "market": x, "wage": x}} with measured values relative to Ufa (1.0). Empty until real data arrive.
OVERRIDES = {}

_ufa_population = None


def _ratio(city):
    global _ufa_population
    if _ufa_population is None:
        _ufa_population = float(geo.get_city("ufa")["population_estimate"])
    return float(city["population_estimate"]) / _ufa_population


def indices(city_id):
    """Price indices of a city relative to Ufa (1.0): construction cost, market price of housing and land, wages."""
    city = geo.get_city(city_id)
    if city is None:
        raise ValueError("unknown city")
    r = _ratio(city)
    construction = min(1.0, max(0.70, 0.70 + 0.30 * r ** 0.25))      # ESTIMATE: smaller towns build a little cheaper
    market = min(1.0, max(0.40, 0.35 + 0.65 * r ** 0.30))             # ESTIMATE: housing in small towns is much cheaper than in Ufa
    wage = min(1.05, max(0.70, 0.75 + 0.25 * r ** 0.20))
    if any(word in city.get("specialization", "") for word in WAGE_BONUS_WORDS):
        wage = min(1.05, wage + 0.08)
    out = {"construction": round(construction, 3), "market": round(market, 3), "wage": round(wage, 3)}
    out.update(OVERRIDES.get(city_id, {}))
    return out


def to_game(real_roubles):
    return int(round(real_roubles / REAL_PER_GAME))


def build_cost(structure, area_m2, city_id="ufa"):
    """Construction cost of `area_m2` of a structure type in a city, in game roubles."""
    return to_game(BUILD_COST_M2_UFA[structure] * area_m2 * indices(city_id)["construction"])


def market_price_m2(city_id="ufa"):
    """Sale price of a new-build m2 in game roubles."""
    return to_game(MARKET_PRICE_M2_UFA * indices(city_id)["market"])


def rent_m2_month(city_id="ufa"):
    return round(RENT_M2_MONTH_UFA * indices(city_id)["market"] / REAL_PER_GAME, 2)


def wage(city_id="ufa", base_wage=1500):
    """The average monthly wage of a city in game roubles (the republic's average is BASE_WAGE)."""
    return int(round(base_wage * indices(city_id)["wage"]))


def table():
    out = []
    for c in geo.cities():
        i = indices(c["id"])
        out.append({"id": c["id"], "name": c["name"], "population_estimate": c["population_estimate"], **i,
                    "market_price_m2": market_price_m2(c["id"]), "rent_m2_month": rent_m2_month(c["id"]), "wage": wage(c["id"])})
    return out
