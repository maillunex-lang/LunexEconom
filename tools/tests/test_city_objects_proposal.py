"""Regression tests for V2-CITY-DESIGN (no database, server or client changes)."""
from __future__ import annotations
import copy
import tempfile
import unittest
from pathlib import Path
from tools.validate_city_objects_proposal import (
    load_proposal, read_json, validate, generate, digest, footprint,
    ufa_district, virtual_road, trunk_edges, objects_in_cell, objects_in_chunk, ROOT
)

class CityProposalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_proposal()
        cls.world = read_json(ROOT / "server/data/cities.json")
        cls.cities = cls.world["cities"]

    def _gen(self, city, level, **kwargs):
        return generate(city,level,self.data["catalog"],self.data["rules"],
                        self.world["seed"],self.cities,self.data["districts_ufa"],**kwargs)

    def test_validator_accepts_baseline(self):
        self.assertEqual(validate(self.data), [])

    def test_types_and_service_references(self):
        rows = self.data["catalog"]["objects"]
        self.assertEqual(len(rows),22)
        self.assertEqual(len({o["id"] for o in rows}),22)
        self.assertEqual({o["service"] for o in rows},{"health","education","transport"})

    def test_repeatability_and_snapshot_hashes(self):
        for city, example in zip(self.cities[:3],self.data["examples"]["cities"]):
            self.assertEqual(city["id"],example["city_id"])
            for level in (1,2,3):
                first, second = self._gen(city,level), self._gen(city,level)
                self.assertEqual(first,second)
                self.assertEqual(first,example["levels"][str(level)]["objects"])
                self.assertEqual(digest(first),example["levels"][str(level)]["sha256"])

    def test_growth_never_moves_old_objects(self):
        for city in self.cities[:3]:
            one,two,three=[self._gen(city,n) for n in (1,2,3)]
            self.assertEqual(two[:len(one)],one)
            self.assertEqual(three[:len(two)],two)

    def test_owned_or_reserved_cells_block_without_reflow(self):
        city=self.cities[0]
        normal=self._gen(city,2)
        self.assertTrue(normal)
        blocked=footprint(normal[0])
        after=self._gen(city,2,occupied=blocked)
        self.assertNotIn(normal[0],after)
        self.assertFalse(set().union(*(footprint(o) for o in after)) & blocked)
        self.assertEqual(after,[obj for obj in normal if not footprint(obj)&blocked])

    def test_reject_float_json(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/"float.json"
            p.write_text('{"price":1.2}',encoding="utf8")
            with self.assertRaises(ValueError):
                read_json(p)

    def test_reject_nonexistent_service(self):
        bad=copy.deepcopy(self.data)
        bad["catalog"]["objects"][0]["service"]="teleport"
        self.assertTrue(any("unknown service" in e for e in validate(bad)))

    def test_reject_district_share_mismatch(self):
        bad=copy.deepcopy(self.data)
        bad["districts_ufa"]["districts"][0]["pop_permille"]+=1
        self.assertTrue(any("population shares" in e for e in validate(bad)))

    def test_reject_changed_snapshot(self):
        bad=copy.deepcopy(self.data)
        bad["examples"]["cities"][0]["levels"]["1"]["objects"][0]["x"]+=1
        self.assertTrue(any("example mismatch" in e for e in validate(bad)))

    def test_district_partition_all_cells(self):
        ufa=self.cities[0]
        known={d["id"] for d in self.data["districts_ufa"]["districts"]}
        for y in range(-12,13):
            for x in range(-12,13):
                self.assertIn(ufa_district(x,y,ufa,self.data["districts_ufa"]),known)

    def test_world_road_regression(self):
        ufa=self.cities[0]
        locations={c["id"]:c for c in self.cities}
        edges=trunk_edges(self.cities)
        self.assertTrue(virtual_road(ufa,1,0,0,locations,edges))
        self.assertTrue(virtual_road(ufa,1,12,12,locations,edges))
        self.assertTrue(virtual_road(ufa,2,15,15,locations,edges))

    def test_chunk_and_cell_crossing_boundary(self):
        # Two-by-two object at 11,11 overlaps four 12x12 chunks.
        obj = dict(x=11,y=11,width=2,height=2,id="sample")
        self.assertEqual(objects_in_cell([obj],12,12),[obj])
        self.assertEqual(objects_in_cell([obj],13,12),[])
        for cx,cy in ((0,0),(1,0),(0,1),(1,1)):
            self.assertEqual(objects_in_chunk([obj],cx,cy),[obj])
        self.assertEqual(objects_in_chunk([obj],-1,0),[])

    def test_city_hall_is_unique_on_each_level(self):
        for city in self.cities[:3]:
            for level in (1,2,3):
                objs=self._gen(city,level)
                self.assertEqual(sum(o["type_id"]=="city_hall" for o in objs),1)

    def test_catalog_limits_trap(self):
        bad=copy.deepcopy(self.data)
        bad["rules"]["max_objects_per_chunk"]=0
        self.assertTrue(any("invalid hard limits" in e for e in validate(bad)))

if __name__=="__main__":
    unittest.main()
