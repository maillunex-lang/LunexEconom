"""Supply registration: links first, city market second, production later."""
from pathlib import Path
from . import core, api

def migrations():
    return [Path(__file__).resolve().parents[1] / 'migrations' / '202611152200_supply_core.sql']

def register(registry):
    registry.flag('supply_enabled', True)
    registry.flag('supply_transport_rub_per_km_unit_draft', 1, 0, 100000)
    registry.flag('supply_port_city_draft', 'ufa')
    registry.flag('supply_port_price_permille_draft', 1000, 250, 2500)
    registry.flag('supply_port_duty_bp_draft', 500, 0, 10000)
    registry.flag('supply_port_fallback_draft', False)
    registry.route('GET','/enterprises/{id}/supply',api.get)
    registry.route('PUT','/enterprises/{id}/supply',api.put)
    def links(conn,day):
        from server.platform.settings import read_settings
        flags=read_settings(conn,registry.flags,registry.flag_constraints)
        if flags['supply_enabled']:
            core.links_day(conn,day,flags)
    registry.tick('daily','supply_links',links,order=20)
