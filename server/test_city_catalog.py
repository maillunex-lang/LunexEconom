"""Catalog of city objects (Expansion 1.0, stage 1)."""
import unittest

import building_dimensions
import city_catalog as cc
import industry_catalog
import zoning

TARGET = {   # the approved starting table: id -> ((w, h), capacity)
    "house_wood": ((1, 1), 4), "house_brick": ((1, 1), 5), "cottage": ((2, 2), 6), "townhouse": ((2, 3), 32),
    "block_2": ((2, 2), 36), "block_3": ((2, 2), 54), "block_5": ((2, 3), 180), "block_9": ((2, 3), 324),
    "block_12": ((3, 3), 540), "block_16": ((3, 3), 768), "complex_modern": ((4, 4), 1200), "quarter": ((6, 6), 2400),
}


class CityCatalogTests(unittest.TestCase):
    def test_housing_matches_the_approved_table(self):
        for oid, (size, capacity) in TARGET.items():
            item = cc.CATALOG[oid]
            self.assertEqual(((item["w"], item["h"]), item["capacity"]), (size, capacity), oid)
            self.assertEqual(item["category"], "housing")

    def test_every_required_municipal_object_exists(self):
        for oid in ("kindergarten", "school", "lyceum", "college", "university", "fap", "polyclinic", "hospital", "administration", "police",
                    "fire_depot", "park", "square", "playground", "sports", "bus_stop", "bus_station", "parking", "landscaping"):
            self.assertIn(oid, cc.CATALOG)

    def test_every_object_has_all_the_parameters_with_sane_integer_values(self):
        for oid, item in cc.CATALOG.items():
            for key in ("id", "name", "category", "w", "h", "capacity", "jobs", "build_cost", "materials", "build_months", "upkeep", "wear_permille_per_month", "model", "stage_models"):
                self.assertIn(key, item, (oid, key))
            self.assertEqual(item["id"], oid)
            for key in ("w", "h", "capacity", "jobs", "build_cost", "upkeep", "build_months", "wear_permille_per_month"):
                self.assertIs(type(item[key]), int, (oid, key))
            self.assertTrue(1 <= item["w"] <= 6 and 1 <= item["h"] <= 6, oid)
            self.assertGreater(item["capacity"], 0, oid)
            self.assertGreater(item["build_cost"], 0, oid)
            self.assertGreaterEqual(item["build_months"], 1, oid)
            self.assertEqual(item["stage_models"], ["foundation", "frame", "finishing", "commissioning"])
            self.assertTrue(item["materials"], oid)
            self.assertTrue(all(type(q) is int and q > 0 for q in item["materials"].values()), oid)

    def test_materials_are_goods_of_the_industry_catalog(self):
        known = {recipe.product for recipe in industry_catalog.RECIPES.values()}
        for oid, item in cc.CATALOG.items():
            self.assertTrue(set(item["materials"]) <= known, (oid, set(item["materials"]) - known))

    def test_the_four_construction_stages_cover_the_whole_build(self):
        self.assertEqual([s for s, _ in cc.STAGES], ["foundation", "frame", "finishing", "commissioning"])
        self.assertEqual(sum(p for _, p in cc.STAGES), 1000)

    def test_bigger_buildings_take_longer_and_taller_housing_is_cheaper_per_resident(self):
        self.assertLess(cc.CATALOG["house_wood"]["build_months"], cc.CATALOG["block_9"]["build_months"])
        self.assertLess(cc.CATALOG["block_9"]["build_months"], cc.CATALOG["quarter"]["build_months"])
        per = lambda oid: cc.CATALOG[oid]["build_cost"] / cc.CATALOG[oid]["capacity"]
        self.assertLess(per("block_16"), per("block_5"))
        self.assertLess(per("block_5"), per("cottage"))

    def test_legacy_kinds_keep_their_footprints_and_the_catalog_never_overrides_them(self):
        for oid, item in cc.CATALOG.items():
            legacy = item["legacy_kind"]
            if legacy:
                self.assertEqual((item["w"], item["h"]), building_dimensions.LEGACY_FOOTPRINTS[legacy], oid)

    def test_all_city_objects_belong_to_the_city_zone_never_the_industrial_one(self):
        for oid, item in cc.CATALOG.items():
            self.assertEqual(item["zone"], "city")
        for legacy in ("school", "hospital", "park"):
            self.assertEqual(set(zoning.ALLOWED[legacy]), set(zoning.CITY_ZONES))

    def test_the_api_serves_the_catalog(self):
        import json, threading, urllib.request
        import game_server
        from http.server import ThreadingHTTPServer
        server = ThreadingHTTPServer(("127.0.0.1", 0), game_server.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        data = json.load(urllib.request.urlopen("http://127.0.0.1:%d/catalog/city" % server.server_address[1]))
        self.assertEqual(data["version"], cc.VERSION)
        self.assertEqual(len(data["objects"]), len(cc.CATALOG))

    def test_view_is_read_only_and_not_buildable_yet(self):
        v = cc.view()
        self.assertFalse(v["enabled"])
        self.assertEqual(len(v["objects"]), len(cc.CATALOG))
        self.assertEqual(len(v["stages"]), 4)


if __name__ == "__main__":
    unittest.main()
