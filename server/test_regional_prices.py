import unittest

import geo
import regional_prices as rp


class RegionalPriceTests(unittest.TestCase):
    def test_the_scale_comes_from_the_average_wage(self):
        self.assertAlmostEqual(74_400 / 1_500, rp.REAL_PER_GAME, delta=1.0)
        self.assertEqual(rp.to_game(5_000_000), 100_000)

    def test_ufa_is_the_benchmark(self):
        self.assertEqual(rp.indices("ufa")["construction"], 1.0)
        self.assertEqual(rp.indices("ufa")["market"], 1.0)
        self.assertEqual(rp.market_price_m2("ufa"), rp.to_game(rp.MARKET_PRICE_M2_UFA))

    def test_smaller_cities_are_cheaper_in_every_index(self):
        cities = sorted(geo.cities(), key=lambda c: -c["population_estimate"])
        for a, b in zip(cities, cities[1:]):
            ia, ib = rp.indices(a["id"]), rp.indices(b["id"])
            self.assertGreaterEqual(ia["market"], ib["market"], (a["id"], b["id"]))
            self.assertGreaterEqual(ia["construction"], ib["construction"], (a["id"], b["id"]))
        for c in geo.cities():
            i = rp.indices(c["id"])
            self.assertTrue(0.7 <= i["construction"] <= 1.0 and 0.4 <= i["market"] <= 1.0 and 0.7 <= i["wage"] <= 1.05, c["id"])

    def test_mining_and_chemical_towns_pay_more_than_agricultural_ones_of_the_same_size(self):
        self.assertGreater(rp.wage("uchaly"), rp.wage("dyurtyuli"))            # mining 36k residents vs agriculture and logistics 31k
        self.assertGreater(rp.wage("baymak"), rp.wage("davlekanovo"))          # a smaller mining town still outpays a larger agricultural one

    def test_overrides_win_over_the_formula(self):
        rp.OVERRIDES["agidel"] = {"market": 0.9}
        try:
            self.assertEqual(rp.indices("agidel")["market"], 0.9)
        finally:
            del rp.OVERRIDES["agidel"]

    def test_unknown_city_is_refused(self):
        with self.assertRaises(ValueError):
            rp.indices("atlantis")

    def test_table_lists_all_twenty_cities(self):
        self.assertEqual(len(rp.table()), 20)


if __name__ == "__main__":
    unittest.main()
