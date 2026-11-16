"""Deterministic, isolated checks for the V2 deep chains proposal."""
import ast
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from tools.sim.chains_deep import run, quality_weighted, allocate_cost, load_scenarios
from tools.sim.chains_deep.model import run_one

ROOT = Path(__file__).resolve().parents[1] / 'sim' / 'data' / 'deep_chains_proposed'


class DeepChainsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run()
        cls.scenarios = {x['id']: x for x in load_scenarios()}

    def test_golden_and_repeatability(self):
        golden = json.loads((ROOT/'golden_24_months.json').read_text())
        self.assertEqual(self.result, golden)
        self.assertEqual(run(), golden)
        self.assertEqual(len(golden['scenarios']), 4)
        for v in golden['scenarios'].values():
            self.assertEqual(len(v['history']), 24)
            self.assertTrue(v['totals']['inventory_conserved'])
            self.assertTrue(v['totals']['cash_conserved'])
            self.assertEqual(v['totals']['output_cost_produced_rub'], v['totals']['output_cost_sold_rub'] + v['totals']['output_cost_disposed_rub'] + v['totals']['output_cost_remaining_rub'])
            for x in v['history']:
                self.assertTrue(all(type(z) is int for z in x.values() if not isinstance(z, str)))
                self.assertTrue(0 <= x['load_bp'] <= 10000)
                self.assertGreaterEqual(x['raw_stock_units'], 0)
                self.assertGreaterEqual(x['finished_stock_units'], 0)

    def test_scenarios(self):
        s=self.result['scenarios']
        self.assertEqual(s['single_recipe']['totals']['avg_load_bp'],10000)
        self.assertEqual(s['recipe_switch']['history'][8]['active_recipe'],'dairy_processing_carton_milk')
        self.assertEqual(s['recipe_switch']['history'][16]['active_recipe'],'dairy_processing_glass_milk')
        self.assertGreater(s['recipe_switch']['totals']['raw_stock_units'],0)
        self.assertEqual(s['recipe_switch']['totals']['switch_lost_batches'],0)
        self.assertGreater(s['byproduct_storage']['totals']['disposal_units'],0)
        self.assertGreater(s['byproduct_storage']['totals']['output_cost_disposed_rub'],0)
        self.assertGreater(s['packaging_bottleneck']['totals']['packaging_shortage_days'],0)
        self.assertLess(s['packaging_bottleneck']['totals']['avg_load_bp'],s['single_recipe']['totals']['avg_load_bp'])

    def test_quality_and_allocation(self):
        self.assertEqual(quality_weighted({'milk':40,'cocoa_powder':4},{'milk':80,'cocoa_powder':50}),77)
        self.assertIsNone(quality_weighted({'milk':40},{'milk':44},{'milk':45}))
        self.assertEqual(quality_weighted({},{}),50)
        self.assertEqual(allocate_cost(101,{'cheese':14,'whey':38},{'cheese':9000,'whey':1000}),{'cheese':91,'whey':10})
        with self.assertRaises(ValueError):
            allocate_cost(100,{'a':1,'b':2},{'a':10000,'b':1000})
        with self.assertRaises(ValueError):
            quality_weighted({'milk':40},{'milk':0})

    def test_recipe_ids_and_whitelist(self):
        products = json.loads((ROOT/'products.json').read_text())
        buildings = json.loads((ROOT/'buildings.json').read_text())
        recipes = json.loads((ROOT/'recipes.json').read_text())
        for items in (products,buildings,recipes):
            self.assertEqual(len({x['id'] for x in items}), len(items))
        for rec in recipes:
            self.assertIn(rec['building'],{b['id'] for b in buildings})
            self.assertTrue(set(rec['inputs']) | set(rec['outputs']) <= {p['id'] for p in products})
            if 'output_cost_allocation_bp' in rec:
                self.assertEqual(sum(rec['output_cost_allocation_bp'].values()), 10000)
                self.assertEqual(set(rec['output_cost_allocation_bp']),set(rec['outputs']))
            if 'ingredient_shares_bp' in rec:
                self.assertEqual(sum(rec['ingredient_shares_bp'].values()),10000)
        with self.assertRaisesRegex(ValueError,'not allowed'):
            run_one(dict(self.scenarios['recipe_switch'],switches=[{'month':1,'recipe':'intruder'}]),1)

    def test_no_float_literals_or_server_imports(self):
        path=Path(__file__).resolve().parents[1]/'sim/chains_deep/model.py'
        tree=ast.parse(path.read_text())
        self.assertFalse(any(isinstance(n,ast.Constant) and isinstance(n.value,float) for n in ast.walk(tree)))
        self.assertFalse(any(isinstance(n,ast.ImportFrom) and n.module and n.module.startswith('server') for n in ast.walk(tree)))


if __name__=='__main__':
    unittest.main()
