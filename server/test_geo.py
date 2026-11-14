"""Deterministic reference geography, highways, and public HTTP API tests."""
import json
import math
import threading
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
import unittest

import geo
import roads
import game_server


class GeoTests(unittest.TestCase):
    def test_20_game_regions_and_cities(self):
        cities = geo.cities()
        regions = geo.regions()
        self.assertEqual(len(cities), 20)
        self.assertEqual(len(regions), 20)
        self.assertEqual(len(set(city["id"] for city in cities)), 20)
        self.assertEqual(cities[0]["name"], "Уфа")
        self.assertEqual((cities[0]["x"], cities[0]["y"]), (0, 0))
        self.assertEqual(len({(c["x"], c["y"]) for c in cities}), 20)
        self.assertTrue(all(region["game_region"] for region in regions))
        self.assertTrue(all(not roads.is_water(c["x"], c["y"]) for c in cities))
        self.assertEqual(cities, geo.cities(), "stable across calls")
        self.assertEqual(geo._grid_point(54.7431, 55.9678), (0, 0))

    def test_known_straight_line_distance(self):
        cities = {city["id"]: city for city in geo.cities()}
        self.assertGreater(geo.distance_km(cities["ufa"], cities["sterlitamak"]), 120)
        self.assertLess(geo.distance_km(cities["ufa"], cities["sterlitamak"]), 130)
        self.assertGreater(geo.distance_km(cities["ufa"], cities["sibay"]), 280)
        self.assertEqual(geo.city_for_cell(0, 0)["id"], "ufa")
        self.assertIsNone(geo.city_for_cell(9999, 9999))

    def test_highways_connected_land_only_and_reproducible(self):
        cities = {city["id"]: city for city in geo.cities()}
        routes = geo.routes()
        self.assertEqual(routes, geo.routes())
        self.assertGreaterEqual(len(routes), 19)
        connected = {"ufa"}
        while True:
            previous = len(connected)
            for route in routes:
                a, b = route["from"], route["to"]
                if a in connected or b in connected:
                    connected.update((a, b))
            if len(connected) == previous:
                break
        self.assertEqual(connected, set(cities))
        for route in routes:
            cells = route["cells"]
            self.assertEqual(cells[0], [cities[route["from"]]["x"], cities[route["from"]]["y"]])
            self.assertEqual(cells[-1], [cities[route["to"]]["x"], cities[route["to"]]["y"]])
            self.assertTrue(all(not roads.is_water(x, y) for x, y in cells))
            self.assertTrue(all(max(abs(x1 - x2), abs(y1 - y2)) == 1
                                for (x1, y1), (x2, y2) in zip(cells, cells[1:])))
            self.assertGreater(route["road_km"], route["distance_km"] * 0.75)
            self.assertLess(route["road_km"], route["distance_km"] * 1.5)
            self.assertGreater(route["travel_months"], 0)

    def test_streets_and_population_only_references(self):
        for city in geo.cities():
            names = geo.streets(city)
            self.assertEqual(len(names), len(set(names)))
            self.assertEqual(names, geo.streets(city))
            self.assertEqual(geo.population(city, 0), city["population_estimate"])
            self.assertEqual(geo.population(city, 24), geo.population(city, 24))
            self.assertLess(abs(geo.population(city, 24) - city["population_estimate"]),
                            city["population_estimate"] * 0.1)
            self.assertIn(city["name"], geo.plot_address(city, city["x"] + 6, city["y"] + 3))

    def test_public_geo_routes_cacheable_json(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), game_server.Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:%d" % server.server_address[1]
        try:
            for path, key, expected in (
                ("/geo/regions", "regions", 20),
                ("/geo/cities", "cities", 20),
                ("/geo/routes", "routes", len(geo.routes())),
            ):
                with urlopen(base + path, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn("public", response.headers["Cache-Control"])
                    payload = json.loads(response.read())
                self.assertEqual(len(payload[key]), expected)
        finally:
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()


if __name__ == "__main__":
    unittest.main()
