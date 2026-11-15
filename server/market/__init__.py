"""City market HTTP and second-phase daily clearing."""
from pathlib import Path
from . import core, api

def migrations():
    return []

def register(registry):
    registry.flag('market_enabled', True)
    registry.route('GET','/market/history',api.history)
    registry.route('GET','/market/{city}',api.city)
    # Registry template resolution presently accepts {id} only. Register
    # exact city routes as well, without changing the shared dispatcher.
    from server.world.core import CITIES
    for city in CITIES:
        registry.route('GET','/market/'+city,api.city_for(city))
    def clear(conn,day):
        from server.platform.settings import read_settings
        flags=read_settings(conn,registry.flags,registry.flag_constraints)
        if flags['market_enabled'] and flags['supply_enabled']:
            core.clear_day(conn,day,flags)
    registry.tick('daily','supply_market',clear,order=30)
