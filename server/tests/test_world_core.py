"""Pure-city metadata validation, road network, compatibility and reference vectors."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from server.world import core
from server.world.cities import DATA, load_cities
from server.world.generator import noise, terrain, radius_at_level, zone, connected
from server.game_server import build_registry


class WorldCoreTests(unittest.TestCase):
    def test_city_data_and_reference_indices(self):
        doc=load_cities()
        self.assertEqual(len(doc['cities']),20)
        self.assertEqual(len(core.CITIES),20)
        self.assertEqual(len(core.TRUNK),19)
        self.assertEqual(core.CITIES['ufa']['indices_bp']['salary'],10000)
        self.assertEqual(core.CITIES['ufa']['x'],0)
        self.assertEqual(core.CITIES['ufa']['y'],0)
        self.assertTrue(all(c['balance']=='draft' for c in doc['cities']))

    def test_invalid_descriptor_blocks_startup(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'cities.json'
            shutil.copyfile(DATA,path)
            obj=json.loads(path.read_text())
            obj['cities'][1]['id']='ufa'
            path.write_text(json.dumps(obj))
            with self.assertRaisesRegex(ValueError,'City IDs'):
                load_cities(path)
            obj=json.loads(DATA.read_text())
            obj['cities'][1]['indices_bp']['land']=1.5
            path.write_text(json.dumps(obj))
            with self.assertRaises(ValueError):
                load_cities(path)

    def test_terrain_reference_vectors(self):
        path=Path(__file__).resolve().parent/'vectors/world_seed_v1.json'
        doc=json.loads(path.read_text())
        for cell in doc['cells']:
            with self.subTest(cell=cell):
                self.assertEqual(terrain(doc['seed'],cell['x'],cell['y']),cell['terrain'])
                self.assertEqual(noise(doc['seed'],cell['x'],cell['y']),cell['noise'])
        for cell in doc['zones']:
            self.assertEqual(zone(cell['x'],cell['y'],0,0,12,cell['level']),cell['zone'])
        self.assertEqual([radius_at_level(12,i) for i in range(1,7)],doc['radii'])

    def test_zoning_never_reassigns_existing_ring(self):
        for x in range(-12,13):
            for y in range(-12,13):
                self.assertEqual(zone(x,y,0,0,12,1),zone(x,y,0,0,12,6))
        self.assertEqual([radius_at_level(12,i) for i in range(1,7)],[12,15,19,24,30,38])
        self.assertEqual(zone(12,0,0,0,12,1),'industrial')
        self.assertEqual(zone(13,0,0,0,12,1),'free')
        self.assertEqual(zone(13,0,0,0,12,2),'industrial')

    def test_trunk_connected_and_road_metrics(self):
        self.assertEqual(core.routes('ufa','ufa')['distance_meters'],0)
        for city_id in core.CITIES:
            route=core.routes('ufa',city_id)
            self.assertEqual(route['cities'][0],'ufa')
            self.assertEqual(route['cities'][-1],city_id)
            self.assertEqual(route['distance_meters']%20,0)
            self.assertGreaterEqual(route['game_minutes'],0)
        with self.assertRaisesRegex(ValueError,'unknown_city'):
            core.routes('ufa','not_a_city')
        self.assertFalse(connected({(0,0),(2,0)},(0,0),(2,0)))

    def test_land_unit_prices_and_unbounded_grid(self):
        self.assertEqual(core.parcel_price('ufa','residential'),15000)
        self.assertEqual(core.parcel_price('ufa','industrial'),17250)
        self.assertEqual(core.parcel_origin(-1,-2),(-6,-12))
        self.assertEqual(core.nearest_city(0,0)['id'],'ufa')

    def test_registry_world_hooks_and_flags(self):
        registry=build_registry()
        self.assertTrue(registry.flags['world_enabled'])
        self.assertEqual(registry.flags['world_growth_threshold_bp'],6000)
        self.assertIn(('GET','/world/cities/ufa'),registry.routes)
        self.assertIn(('POST','/land/buy'),registry.routes)
        self.assertIn(('GET','/admin/world/growth'),registry.routes)
        self.assertTrue(any(name=='world_growth'
                            for _,name,_ in registry.tick_handlers['monthly']))
        self.assertTrue(any('world_core' in p.name
                            for p in registry.modules for p in p.migrations()))


if __name__=='__main__':
    unittest.main()
