#!/usr/bin/env python3
"""Structural M1 validation, not a substitute for PostgreSQL integration tests."""
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server.enterprises.core import catalog
from server.retail import core
from server.game_server import build_registry

ROOT=Path(__file__).resolve().parents[1]
MIGRATION=ROOT/'server/migrations/202611152300_retail_core.sql'

def main():
    reg=build_registry()
    assert len(reg.modules)==9
    daily={name:order for order,name,_ in reg.tick_handlers['daily']}
    assert daily['supply_market']<daily['retail']<daily['enterprise_production']
    assert ('GET','/retail/ratings') in reg.routes
    for method,route in [('GET','/enterprises/{id}/cells'),('PUT','/enterprises/{id}/cells'),
                         ('GET','/enterprises/{id}/sales')]:
        assert (method,route) in reg.routes
    assert MIGRATION.is_file()
    sql=MIGRATION.read_text()
    for table in ('retail_cells','retail_sales_daily','retail_alerts','retail_receipts','retail_month_receipts'):
        assert re.search(r'CREATE TABLE\s+'+table+r'\b',sql),table
    buildings=[b for b in catalog().data['buildings'] if b.get('role')=='retail']
    assert len(buildings)>=3
    assert all(b.get('retail_cells',0)>0 and b.get('allowed_goods') for b in buildings)
    bread=catalog().index['products']['bread']
    assert core.rating(bread,90,50)==70
    assert core.vat_parts(9000)==(8181,819)
    print('V2-06 retail validator: OK (structural, arithmetic, registration); PostgreSQL separately required')

if __name__=='__main__':
    main()
