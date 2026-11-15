"""Pure integer supply invariants, no production DB touched."""
import unittest
from server.market.core import clearing_price
from server.supply.core import _int

class SupplyMathTests(unittest.TestCase):
    def test_price_corridor(self):
        for price in (1,25,45,90,3500):
            for demand,supply in ((0,0),(0,100),(100,0),(100,100),(200,100),(100,200),(1000000,1)):
                result=clearing_price(price,demand,supply)
                self.assertGreaterEqual(result,max(1,price*250//1000))
                self.assertLessEqual(result,max(1,price*2500//1000))
    def test_reference_balance(self):
        self.assertEqual(clearing_price(25,100,100),25)
        self.assertEqual(clearing_price(45,200,100),90)
        self.assertEqual(clearing_price(90,0,100),22)
    def test_type_checks(self):
        for value in (True,False,1.1,'100',-1):
            with self.assertRaises(ValueError):
                _int(value)
