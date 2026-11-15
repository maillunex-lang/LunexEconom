"""Manual terrain parity and one-range-query access prefetch."""
import os
import tempfile
import unittest
from unittest import mock

import game_server
import citygen
import terrain_rules
import roads

class TerrainParityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old=game_server.DB
        game_server.DB=os.path.join(self.tmp.name,'world.sqlite3')
    def tearDown(self):
        game_server.DB=self.old
        self.tmp.cleanup()

    def test_manual_water_and_clear_override_procedural(self):
        with game_server.connect() as db:
            water_cell=next((x,800) for x in range(150,400) if roads.is_water(x,800))
            dry_cell=next((x,800) for x in range(150,400) if not roads.is_water(x,800) and not roads.is_base_road(x,800))
            db.execute("INSERT INTO terrain_edits(x,y,kind,editor,created,manual) VALUES(?,?,?,?,?,1)",(*water_cell,'clear','tester',1))
            db.execute("INSERT INTO terrain_edits(x,y,kind,editor,created,manual) VALUES(?,?,?,?,?,1)",(*dry_cell,'water','tester',1))
            overrides=terrain_rules.preload(db,'?',(150,400,799,801))
            self.assertFalse(terrain_rules.is_water(*water_cell,overrides))
            self.assertTrue(terrain_rules.is_water(*dry_cell,overrides))
            self.assertTrue(terrain_rules.manual(*dry_cell,overrides))
            self.assertIsNone(roads.plan_access([water_cell],{(water_cell[0]-1,water_cell[1])},set(),1000,overrides)[0])
            self.assertEqual(roads.plan_access([dry_cell],set(),set(),1000,overrides)[0],'water')

    def test_citygen_never_uses_manual_lot(self):
        x,y=citygen.plan('ufa')[0]
        with game_server.connect() as db:
            db.execute('INSERT INTO terrain_edits VALUES(?,?,?,?,?,1)',(x,y,'grass','tester',1))
            citygen.seed_city(db,'?','ufa',1800000000,max_new=16)
            self.assertIsNone(db.execute('SELECT object_id FROM cells WHERE x=? AND y=?',(x,y)).fetchone())

if __name__=='__main__':unittest.main()