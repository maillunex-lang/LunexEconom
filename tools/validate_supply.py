"""Read-only structural validator for supply/market integration."""
from pathlib import Path
import ast
import re

ROOT=Path(__file__).resolve().parents[1]
FILES=[
 'server/supply/__init__.py','server/supply/core.py','server/supply/api.py',
 'server/market/__init__.py','server/market/core.py','server/market/api.py',
 'server/tests/test_supply_math.py',
]
def validate():
    for name in FILES:
        ast.parse((ROOT/name).read_text(encoding='utf-8'),filename=name)
    sql=(ROOT/'server/migrations/202611152200_supply_core.sql').read_text()
    for table in ('supply_links','market_prices','shipments','supply_daily_needs','supply_receipts'):
        if not re.search(r'CREATE TABLE\s+'+table+r'\s*\(',sql):
            raise ValueError('missing table '+table)
    server=(ROOT/'server/game_server.py').read_text()
    if 'supply, market' not in server or '(platform,ledger,clock,world,catalog,supply,market,enterprises)' not in server:
        raise ValueError('supply module not registered before production')
    print('Supply structural validation OK (does not replace PostgreSQL integration tests)')
if __name__=='__main__':validate()
