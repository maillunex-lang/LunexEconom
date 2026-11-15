"""V2-06 retail deterministic integer math and schema checks."""
import unittest
from server.retail import core
from server.game_server import build_registry


class RetailUnitTests(unittest.TestCase):
    def setUp(self):
        self.bread=core.catalog().index['products']['bread']
        self.store=core.building_details('grocery_store')

    def cell(self, index=0, good='bread', price=90, minimum=100, slot=None):
        return dict(cell_index=index,product_id=good,price=price,min_stock=minimum,supply_link_slot=slot)

    def test_catalog_and_cells(self):
        self.assertEqual(self.store['retail_cells'],9)
        self.assertEqual(core.building_details('supermarket')['retail_cells'],16)
        self.assertEqual(core.building_details('clothing_store')['retail_cells'],9)
        with self.assertRaises(ValueError):
            core.building_details('field')
        cells=core.validate_cells(self.store,[self.cell(2),self.cell(1)])
        self.assertEqual([c['cell_index'] for c in cells],[1,2])
        cases=([self.cell(0),self.cell(0)], [self.cell(9)],
               [self.cell(good='grain')], [self.cell(price=0)],
               [self.cell(price=True)], [self.cell(price=1.0)],
               [self.cell(minimum=-1)], [self.cell(slot=4)],
               [self.cell()]*10)
        for case in cases:
            with self.subTest(case=case),self.assertRaises(ValueError):
                core.validate_cells(self.store,case)

    def test_rating_quality_price_and_share(self):
        original=core.rating(self.bread,90,50)
        self.assertEqual(original,70)
        low=core.rating(self.bread,150,50)
        high=core.rating(self.bread,60,50)
        self.assertLess(low,original)
        self.assertEqual(high,original)  # capped at 100; no undeserved bonus
        self.assertGreater(core.rating(self.bread,90,80),original)
        first=core.attractiveness(original)
        second=core.attractiveness(low)
        shares=core.split_demand(1000,[((1,0),first),((2,0),second)])
        self.assertGreater(shares[1,0],shares[2,0])
        self.assertEqual(sum(shares.values()),1000)
        self.assertEqual(core.split_demand(1,[((1,0),70),((2,0),70)]),{(1,0):1,(2,0):0})

    def test_demand_and_vat_integer(self):
        self.assertGreater(core.city_demand(1150000,self.bread,90,70),0)
        self.assertGreater(core.city_demand(1150000,self.bread,90,70),
                           core.city_demand(1150000,self.bread,150,70))
        self.assertEqual(core.vat_parts(9000),(8181,819))
        self.assertEqual(core.vat_parts(0),(0,0))
        self.assertEqual(core.vat_parts(110),(100,10))

    def test_registered_order(self):
        r=build_registry()
        daily={name:order for order,name,_ in r.tick_handlers['daily']}
        self.assertEqual(daily['retail'],35)
        self.assertLess(daily['supply_market'],daily['retail'])
        self.assertLess(daily['retail'],daily['enterprise_production'])
        self.assertIn(('GET','/retail/ratings'),r.routes)
