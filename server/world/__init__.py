"""Server-authoritative sparse world, land registry, city growth and route API."""
from . import core, api

def migrations():
    return core.migrations()

def bootstrap(conn):
    return core.bootstrap(conn)

def register(registry):
    # Loading the module validates all 20 descriptors before any database use.
    registry.flag('world_enabled', True)
    registry.flag('world_growth_enabled', True)
    registry.flag('world_growth_threshold_bp', 6000, 1, 10000)
    registry.flag('world_growth_min_buildings', 10, 1, 1000000)
    registry.flag('world_growth_population_step', 10000, 0, 100000000)
    registry.route('GET','/world/cities',api.list_cities)
    for city_id in core.CITIES:
        registry.route('GET','/world/cities/'+city_id,api.city_one(city_id))
    registry.route('GET','/world/chunk',api.get_chunk)
    registry.route('GET','/world/events',api.events)
    registry.route('GET','/world/routes',api.get_routes)
    registry.route('GET','/land/parcels',api.parcels)
    registry.route('POST','/land/buy',api.buy)
    registry.route('POST','/world/roads',api.build_roads)
    registry.route('GET','/admin/world/growth',api.admin_growth)
    registry.route('POST','/admin/world/growth',api.admin_growth)
    def grow(conn,month_index):
        from server.platform.settings import read_settings
        flags=read_settings(conn,registry.flags,registry.flag_constraints)
        if flags['world_enabled'] and flags['world_growth_enabled']:
            core.grow_month(conn,month_index,
                flags['world_growth_threshold_bp'],
                flags['world_growth_min_buildings'],
                flags['world_growth_population_step'])
    registry.tick('monthly','world_growth',grow,order=80)
