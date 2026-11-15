"""Target corridors of the economic simulator (docs/BALANCE_PLAN.md): what a healthy game economy looks like, as data.

A corridor is (low, high) for an indicator in a stable game state (after the warm-up). Hard invariants are separate: they must hold exactly
(ledger sum 0, no negative stock, ...). `status` says whether tools/balance_sim.py already measures the indicator ("measured") or the block that
introduces it is still to come ("planned"). Values are the starting targets of the balance and are tuned by changing THIS file and the parameters
listed in the plan, not by editing game code.
"""
WARMUP_MONTHS = 12
HORIZON_MONTHS = 72

INVARIANTS = (
    "ledger_sum", "unbalanced_tx", "wallet_mismatch", "negative_players", "negative_stock",
)

# indicator: (low, high, unit, status, metric field of tools/balance_sim.py or the planned source)
CORRIDORS = {
    "unemployment": (0.03, 0.12, "share of the labour force", "measured", "unemployment_ppm"),
    "population_growth_year": (-0.02, 0.10, "share per year", "measured", "population"),
    "inflation_year": (0.0, 0.10, "share per year (basket of goods)", "planned", "EX-09 price index"),
    "wage_share_of_revenue": (0.25, 0.60, "wages / revenue of a producing company", "planned", "company reports"),
    "chain_payback_months": (6, 36, "months to recover the build cost of a normal chain", "planned", "forecast per building"),
    "profit_margin_company": (0.02, 0.25, "profit / revenue, healthy company", "planned", "company_reports table: add to the simulator"),
    "bankruptcies_per_100_companies_year": (0.0, 8.0, "per 100 companies per year", "measured", "bankruptcies"),
    "tax_share_of_gdp": (0.10, 0.35, "taxes / value added", "measured", "tax_paid"),
    "city_budget_months_of_expenses": (1.0, 12.0, "budget / monthly city expenses", "measured", "city_budget"),
    "housing_share_of_family_spending": (0.15, 0.40, "housing costs / household income", "planned", "EX-05 households"),
    "mortgage_burden": (0.0, 0.45, "mortgage payment / household income", "planned", "EX-09 loans"),
    "loan_rate_year": (0.05, 0.40, "annual rate incl. risk premium", "planned", "EX-09 banks"),
    "price_vs_reference": (0.5, 2.0, "market price / reference price of a good", "measured", "*_price"),
    "storage_fill": (0.0, 0.95, "stock / warehouse capacity", "planned", "inventory table: add to the simulator"),
    "step_ms_20_cities": (0.0, 500.0, "monthly step time in ms, 20 active cities", "measured", "step_ms"),
}

# Scenarios every block must add to the simulator (docs/BALANCE_PLAN.md, section 5).
SCENARIOS = (
    "npc_baseline", "idle_player", "rotate_player", "hoarder", "credit_boom", "shop_chain",
    "construction_boom", "land_speculation", "housing_shortage", "recession", "inflation_shock", "multi_city_trade",
)


def check(indicators):
    """Compare measured indicators with the corridors. Returns [(name, value, low, high)] for every indicator outside its corridor."""
    out = []
    for name, value in indicators.items():
        if name in CORRIDORS:
            low, high = CORRIDORS[name][0], CORRIDORS[name][1]
            if not low <= value <= high:
                out.append((name, value, low, high))
    return out
