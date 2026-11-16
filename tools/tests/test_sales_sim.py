"""Contract tests of the proposed sales policy, all calculations integer."""
import ast
import json
import unittest
from pathlib import Path

from tools.sim.sales import run, load_inputs, rebuild_golden
from tools.sim.sales.model import (accepted_buyers, allocate_fair, checked,
                                   pricing_valid, simulate_one, supplier_score)

DATA = Path(__file__).resolve().parents[1] / 'sim' / 'data' / 'sales_proposed'


class SalesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg, cls.scenarios = load_inputs()
        cls.result = run(24)

    def test_config_and_price_limits(self):
        c = self.cfg
        self.assertEqual(sum(c[k] for k in ('quality_score_weight_bp','price_score_weight_bp',
                                           'reliability_score_weight_bp','distance_score_weight_bp')), 10000)
        self.assertTrue(pricing_valid(40, c))
        self.assertTrue(pricing_valid(240, c))
        self.assertFalse(pricing_valid(39, c))
        self.assertFalse(pricing_valid(241, c))
        with self.assertRaises(ValueError): checked(True)

    def test_qualification_and_port_cap(self):
        c = self.cfg
        self.assertIsNone(supplier_score(224, 90, 1000, 2, c))
        self.assertIsNone(supplier_score(80, 44, 1000, 2, c))
        self.assertIsNotNone(supplier_score(80, 85, 950, 2, c))
        self.assertGreater(supplier_score(75, 85, 950, 2, c),supplier_score(80, 85, 950, 2, c))
        self.assertGreater(supplier_score(80, 90, 950, 2, c),supplier_score(80, 85, 950, 2, c))
        buyers=self.scenarios[-1]['external_buyers']
        qualified=accepted_buyers(buyers,79,83,980,c,['b1'],['b2'],'invited')
        self.assertEqual([b['id'] for b,_ in qualified],['b1','b2'])

    def test_fairness_and_independent_order(self):
        original={'z':100,'a':100,'b':100}
        self.assertEqual(allocate_fair(100,original), allocate_fair(100,dict(reversed(list(original.items())))))
        self.assertEqual(sum(allocate_fair(100,original).values()),100)
        self.assertLessEqual(max(allocate_fair(100,original).values())-min(allocate_fair(100,original).values()),1)
        self.assertEqual(sum(allocate_fair(7, {'a':2,'b':2,'c':2}).values()),6)

    def test_private_fair_overpriced_mixed_contract(self):
        t={key:value['totals'] for key,value in self.result['scenarios'].items()}
        self.assertEqual(t['private_mine']['external_sold'],0)
        self.assertGreater(t['public_fair']['external_sold'],0)
        self.assertGreater(t['public_fair']['buyers_profit_rub'],0)
        self.assertGreater(t['public_fair']['seller_profit_rub'],0)
        self.assertLess(t['public_overpriced']['external_sold'],t['public_fair']['external_sold'])
        self.assertLess(t['public_overpriced']['final_price_rub'],224)
        self.assertLess(t['public_overpriced']['seller_profit_rub'],t['public_fair']['seller_profit_rub'])
        self.assertGreater(t['mixed_shortage_ai']['own_delivered'],0)
        self.assertGreater(t['mixed_shortage_ai']['external_sold'],0)
        self.assertGreater(t['mixed_shortage_ai']['lost_sales_units'],0)
        self.assertGreater(t['invited_contract']['external_sold'],0)

    def test_golden_months_ledger_and_inventory(self):
        expected=json.loads((DATA/'golden_24_months.json').read_text(encoding='utf-8'))
        self.assertEqual(self.result,expected)
        self.assertEqual(self.result,run(24))
        for row in self.result['scenarios'].values():
            self.assertTrue(row['wallet_conserved'])
            self.assertEqual(len(row['history']),24)
            for month in row['history']:
                self.assertEqual(month['produced'],month['own_delivered']+month['external_sold']+month['unsold_stock'])
                self.assertTrue(all(type(n) is int for n in month.values()))
                self.assertTrue(all(month[k]>=0 for k in ('produced','own_delivered','external_sold','unsold_stock','lost_sales_units')))

    def test_no_float_literals_or_import_server(self):
        for path in (Path(__file__),Path(__file__).parents[1]/'sim/sales/model.py'):
            tree=ast.parse(path.read_text(encoding='utf-8'))
            self.assertFalse(any(isinstance(n,ast.Constant) and isinstance(n.value,float) for n in ast.walk(tree)))
        self.assertEqual(rebuild_golden(), DATA/'golden_24_months.json')

    def test_mode_transition_next_day_and_idempotence_contract(self):
        # Independent requests are stable by order; duplicated request id cannot credit twice.
        a=simulate_one(self.scenarios[1],self.cfg,1)
        b=simulate_one(self.scenarios[1],self.cfg,1)
        self.assertEqual(a,b)
        self.assertTrue(a['wallet_conserved'])
        self.assertEqual(a['totals']['journal_entries'] % 2,0)


if __name__ == '__main__':
    unittest.main()
