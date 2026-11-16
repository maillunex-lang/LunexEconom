"""Sales modes: isolated supply extension, off by default."""
from pathlib import Path
from . import api, core


def migrations():
    return [Path(__file__).resolve().parents[1] / 'migrations' /
            '202611161430_sales_modes.sql']


def register(registry):
    registry.flag('supply_sales_modes_enabled', False)
    registry.flag('sales_price_min_bp', 5000, 1, 10000)
    registry.flag('sales_price_max_bp', 30000, 10000, 100000)
    registry.flag('sales_price_step_rub', 1, 1, 1000)
    registry.flag('sales_market_share_cap_bp', 4000, 0, 10000)
    registry.flag('sales_score_cutoff', 570, 0, 1000)
    registry.route('GET', '/enterprises/{id}/sales-policy/{product}', api.policy_get)
    registry.route('PUT', '/enterprises/{id}/sales-policy/{product}', api.policy_put)
    registry.route('GET', '/supply/offers', api.offers)
    registry.route('POST', '/contracts', api.contract)
    registry.route('GET', '/enterprises/{id}/sales-daily', api.daily)
    registry.route('GET', '/supply/quotes', api.quotes)
    registry.route('POST', '/supply/purchase', api.purchase)
    def daily_sales(conn, day):
        from server.platform.settings import read_settings
        settings = read_settings(conn, registry.flags, registry.flag_constraints)
        if settings['supply_enabled'] and settings['supply_sales_modes_enabled']:
            core.clear_day(conn, day, settings)
    # Called immediately before links by the existing supply tick so the
    # public daily tick order contract stays stable for legacy consumers.
    registry.sales_daily_prelink = daily_sales
