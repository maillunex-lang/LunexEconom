"""V2-06 server retail, integer arithmetic and receipts."""
from pathlib import Path
from . import api, core

def migrations():
    return [Path(__file__).resolve().parents[1] / 'migrations' / '202611152300_retail_core.sql']

def register(registry):
    registry.flag('retail_enabled', True)
    registry.flag('retail_vat_bp_draft', 1000, 0, 10000)
    registry.route('GET','/enterprises/{id}/cells',api.get_cells)
    registry.route('PUT','/enterprises/{id}/cells',api.put_cells)
    registry.route('GET','/enterprises/{id}/sales',api.sales)
    registry.route('GET','/retail/ratings',api.ratings)
    def daily(conn,day):
        from server.platform.settings import read_settings
        flags=read_settings(conn,registry.flags,registry.flag_constraints)
        if flags['retail_enabled']:
            core.advance_day(conn,day,flags['retail_vat_bp_draft'])
    def monthly(conn,month):
        from server.platform.settings import read_settings
        if read_settings(conn,registry.flags,registry.flag_constraints)['retail_enabled']:
            core.close_month(conn,month,read_settings(conn,registry.flags,registry.flag_constraints)['retail_vat_bp_draft'])
    registry.tick('daily','retail',daily,order=35)
    registry.tick('monthly','retail_vat',monthly,order=60)
