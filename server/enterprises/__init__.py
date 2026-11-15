"""Enterprise module."""
from pathlib import Path
from . import core, api

def migrations():
    base=Path(__file__).resolve().parents[1] / 'migrations'
    return [base / '202611152100_enterprises_core.sql', base / '202611152101_enterprises_arrears.sql', base / '202611152350_enterprises_stage_payments.sql']

def register(registry):
    registry.flag('enterprise_enabled', True)
    registry.flag('enterprise_staffing_bp_draft', 10000, 0, 10000)
    registry.flag('enterprise_salary_worker_draft', 100, 0, 1000000)
    registry.flag('enterprise_wear_month_draft', 1, 0, 100)
    registry.flag('enterprise_admin_stock_draft', False)
    registry.route('POST','/enterprises',api.create)
    registry.route('GET','/enterprises',api.list_own)
    registry.route('GET','/enterprises/plan',api.plan)
    registry.route('GET','/enterprises/{id}',api.one)
    registry.route('POST','/enterprises/{id}/settings',api.settings)
    registry.route('POST','/enterprises/{id}/sell',api.sell)
    registry.route('POST','/enterprises/{id}/demolish',api.demolish)
    registry.route('GET','/enterprises/{id}/report',api.report)
    registry.route('POST','/admin/enterprises/{id}/inventory',api.admin_stock)
    def daily(conn,day):
        from server.platform.settings import read_settings
        flags=read_settings(conn,registry.flags,registry.flag_constraints)
        if flags['enterprise_enabled']:
            core.advance_day(conn,day,flags['enterprise_staffing_bp_draft'])
    def monthly(conn,month):
        from server.platform.settings import read_settings
        flags=read_settings(conn,registry.flags,registry.flag_constraints)
        if flags['enterprise_enabled']:
            core.close_month(conn,month,flags['enterprise_salary_worker_draft'],flags['enterprise_wear_month_draft'])
    registry.tick('daily','enterprise_production',daily,order=40)
    registry.tick('monthly','enterprise_finances',monthly,order=40)
