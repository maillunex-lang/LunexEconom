"""Pure world generator tests (no PostgreSQL required)."""
import unittest

from server.world.generator import (
    CHUNK_CELLS, build_allowed, chunk, connected, noise,
    radius_at_level, terrain, travel_game_hours, zone,
)


class WorldGeneratorTests(unittest.TestCase):
    def test_determinism_and_negative_chunks(self):
        for cx, cy in ((0, 0), (-1, -1), (100000, -100000)):
            result = chunk(20261115, cx, cy)
            self.assertEqual(result, chunk(20261115, cx, cy))
            self.assertEqual(len(result["terrain"]), CHUNK_CELLS)
            self.assertTrue(all(len(row) == CHUNK_CELLS for row in result["terrain"]))

    def test_no_float(self):
        for fn, args in ((noise, (1, 1.5, 2)), (chunk, (1, 0.5, 0))):
            with self.assertRaises(TypeError):
                fn(*args)

    def test_growth_and_zones(self):
        radii = [radius_at_level(20, level) for level in range(1, 7)]
        self.assertEqual(radii, [20, 25, 32, 40, 50, 63])
        self.assertEqual(zone(0, 0, 0, 0, 20, 1), "center")
        self.assertEqual(zone(80, 0, 0, 0, 20, 1), "free")
        self.assertEqual(zone(25, 0, 0, 0, 20, 2), "industrial")
        for x in range(-20, 21):
            for y in range(-20, 21):
                self.assertEqual(zone(x, y, 0, 0, 20, 1),
                                 zone(x, y, 0, 0, 20, 6))

    def test_building_zones(self):
        self.assertTrue(build_allowed({"zones": ["industrial"]}, "industrial"))
        self.assertFalse(build_allowed({"zones": ["industrial"]}, "residential"))

    def test_roads(self):
        self.assertTrue(connected({(0, 0), (1, 0), (2, 0)}, (0, 0), (2, 0)))
        self.assertFalse(connected({(0, 0), (2, 0)}, (0, 0), (2, 0)))
        self.assertEqual(travel_game_hours(85000), 60)
        self.assertEqual(travel_game_hours(0), 0)


if __name__ == "__main__":
    unittest.main()
