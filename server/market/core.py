"""Deterministic integer-only city price discovery (balance: draft)."""
from server.enterprises.core import catalog

def clearing_price(reference, demand, supply):
    if type(reference) is not int or reference<=0 or min(demand,supply)<0:
        raise ValueError('invalid market parameters')
    # Provisional price elasticity: demand/supply ratio in per-mille,
    # with zero demand at corridor floor and zero supply at corridor ceiling.
    if demand==0:
        factor=250
    elif supply==0:
        factor=2500
    else:
        factor=max(250,min(2500, demand*1000//supply))
    return max(1,reference*factor//1000)

def clear_day(conn,day,flags):
    from server.supply.core import market_day
    market_day(conn,day,flags)
