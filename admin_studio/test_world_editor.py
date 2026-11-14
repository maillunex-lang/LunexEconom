import tempfile
import unittest
from livepatch import Store
from world_editor import DEFAULTS, WorldDrafts

class WorldDraftTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.world = WorldDrafts(self.store)
        self.world.save_city("ufa", "Уфа", dict(DEFAULTS))

    def tearDown(self):
        self.temp.cleanup()

    def test_city_and_placement(self):
        self.assertEqual(self.world.city("ufa")["settings"]["population"], 200)
        school = self.world.place("ufa", "school", 10, 20)
        self.assertEqual(school["owner"], "city")
        self.assertEqual(len(self.world.city("ufa")["buildings"]), 1)
        with self.assertRaisesRegex(ValueError, "occupied"):
            self.world.place("ufa", "park", 11, 21)
        self.world.place("ufa", "park", 13, 20)
        self.world.remove("ufa", school["id"])
        self.assertEqual(len(self.world.city("ufa")["buildings"]), 1)

    def test_reject_commercial_and_bad_coords(self):
        with self.assertRaises(ValueError):
            self.world.place("ufa", "factory", 0, 0)
        with self.assertRaises(ValueError):
            self.world.place("ufa", "school", 10000, 10000)
        with self.assertRaises(ValueError):
            self.world.place("ufa", "school", True, 0)

    def test_settings_validation(self):
        for key, value in (("profit_tax", 90), ("month_seconds", 0),
                           ("population", -1), ("growth_per_month", 0.5)):
            settings = dict(DEFAULTS)
            settings[key] = value
            with self.assertRaises(ValueError):
                self.world.save_city("ufa", "Уфа", settings)
        with self.assertRaises(ValueError):
            self.world.save_city("ufa", "Уфа", {"profit_tax": 13})

    def test_forecast_does_not_change_city(self):
        old = self.world.city("ufa")
        result = self.world.forecast("ufa", 12)
        self.assertEqual(result["mode"], "illustrative_draft_only")
        self.assertEqual(self.world.city("ufa"), old)
        self.assertEqual(self.world.export("ufa")["mode"], "review_only")

    def test_audit(self):
        self.world.place("ufa", "park", 0, 0)
        self.assertTrue(any(row["action"] == "draft_place" for row in self.store.audit()))

if __name__ == "__main__":
    unittest.main()
