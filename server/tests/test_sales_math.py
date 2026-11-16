"""Golden parity and pure invariants for opt-in sales engine."""
import unittest
from server.sales import model
from server.sales.core import offer_quantities
from tools.sim.sales import model as golden

CFG,_=golden.load_inputs()


class SalesMathTests(unittest.TestCase):
    def test_golden_price(self):
        for price in range(1,270):
            self.assertEqual(model.price_valid(price,80,5000,30000,1),
                             golden.pricing_valid(price,CFG))

    def test_golden_scoring_grid(self):
        for price in (40,60,80,104,120,240):
            for quality in (0,44,45,49,50,70,100):
                for reliability in (0,200,700,930,1000):
                    for distance in (0,1,4,25):
                        self.assertEqual(model.supplier_score(price,quality,reliability,distance,CFG),
                                         golden.supplier_score(price,quality,reliability,distance,CFG))

    def test_fair_golden_grid(self):
        for available in (0,1,2,3,4,7,15,30,100,220,480):
            for r in (0,1,2,5,17,220):
                demand={'2':r,'4':min(2*r,220),'11':r//2}
                self.assertEqual(model.allocate_fair(available,demand),
                                 golden.allocate_fair(available,demand))

    def test_holding_cap_aggregates(self):
        inputs={'1':100,'2':100,'3':100}
        owners={'1':7,'2':7,'3':8}
        cap=model.cap_requests_by_owner(100,inputs,owners,4000)
        self.assertEqual(cap['1']+cap['2'],40)
        self.assertEqual(cap['3'],40)

    def test_private_no_spot(self):
        self.assertEqual(offer_quantities(100,'private',0,0),(100,0,0))

    def test_mixed_keeps_unused_reserve(self):
        self.assertEqual(offer_quantities(100,'mixed',3000,0),(30,0,70))
        self.assertEqual(offer_quantities(100,'mixed',3000,20),(30,20,50))

    def test_public_contract_first(self):
        self.assertEqual(offer_quantities(100,'public',0,80),(0,80,20))
        self.assertEqual(offer_quantities(100,'public',0,120),(0,100,0))

    def test_prices_integer(self):
        for item in (False,1.5,'80',None,-1):
            with self.assertRaises((ValueError,TypeError)):
                model.price_valid(item,80,5000,30000)

    def test_invalid_score_input(self):
        for quality in (-1,101):
            with self.assertRaises(ValueError):
                model.supplier_score(80,quality,700,3,CFG)

    def test_weighted_model_unchanged(self):
        self.assertEqual(sum(CFG[k] for k in ('quality_score_weight_bp',
            'price_score_weight_bp','reliability_score_weight_bp','distance_score_weight_bp')),10000)

    def test_zero_spot_stock(self):
        self.assertEqual(model.allocate_fair(0,{'1':10,'2':12}),{'1':0,'2':0})

    def test_equal_demands_fairness(self):
        for available in range(0,41):
            a=model.allocate_fair(available,{'1':20,'2':20,'3':20})
            self.assertLessEqual(max(a.values())-min(a.values()),1)

    def test_reject_cap_violation(self):
        with self.assertRaises(ValueError):
            model.allocate_fair(100,{'1':90},20)

    def test_large_integer_allocation(self):
        total=2**50
        a=model.allocate_fair(total,{'1':total,'2':total})
        self.assertEqual(sum(a.values()),total)

    def test_spot_limited(self):
        for qty in (0,1,100,2**20):
            own,contract,spot=offer_quantities(qty,'mixed',10000,0)
            self.assertEqual(spot,0)
            self.assertEqual(own,qty)
            self.assertEqual(contract,0)

class SalesAdditionalSafety(unittest.TestCase):
    def test_only_valid_reserved_quota(self):
        for quota in (0,1000,5000,10000):
            own,contracts,spot=offer_quantities(100,'mixed',quota,20)
            self.assertEqual(own+contracts+spot,100)

    def test_private_reserve_is_all_stock(self):
        for reserve in (0,1000,10000):
            self.assertEqual(offer_quantities(77,'private',reserve,0),(77,0,0))

    def test_public_keeps_no_unapproved_reserve(self):
        self.assertEqual(offer_quantities(55,'public',0,0),(0,0,55))

    def test_overflow_rejects_effective_price(self):
        with self.assertRaises(ValueError):
            model.supplier_score(2**63-1,100,700,10,CFG)

    def test_invalid_holding_cap(self):
        with self.assertRaises(ValueError):
            model.cap_requests_by_owner(100,{'1':20},{'1':1},10001)
