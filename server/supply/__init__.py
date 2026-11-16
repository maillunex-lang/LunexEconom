"""Supply registration: links first, city market second, production later."""
from pathlib import Path
from . import core, api
from server import sales

def migrations():
    return [Path(__file__).resolve().parents[1] / 'migrations' / filename for filename in ('202611152200_supply_core.sql', '202611152210_supply_seller_policy.sql', '202611160830_supply_fuel_failures.sql')] + sales.migrations()

def register(registry):
    sales.register(registry)
    registry.flag('supply_enabled', True)
    registry.flag('logistics_fuel_required', False)
    registry.flag('logistics_fuel_autobuy', True)
    registry.flag('supply_transport_rub_per_km_unit_draft', 1, 0, 100000)
    registry.flag('supply_port_city_draft', 'ufa')
    registry.flag('supply_port_price_permille_draft', 1000, 250, 2500)
    registry.flag('supply_port_duty_bp_draft', 500, 0, 10000)
    registry.flag('supply_port_fallback_draft', False)
    registry.route('GET','/enterprises/{id}/supply',api.get)
    registry.route('PUT','/enterprises/{id}/supply',api.put)
    registry.route('GET','/enterprises/{id}/supply/policy',api.policy_get)
    registry.route('PUT','/enterprises/{id}/supply/policy',api.policy_put)
    def links(conn,day):
        from server.platform.settings import read_settings
        flags=read_settings(conn,registry.flags,registry.flag_constraints)
        if flags['supply_enabled']:
            if flags.get('supply_sales_modes_enabled', False):
                registry.sales_daily_prelink(conn,day)
            core.links_day(conn,day,flags)
    registry.tick('daily','supply_links',links,order=20)
