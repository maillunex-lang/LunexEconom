"""Unit-level enterprise invariants. Integration still requires isolated PostgreSQL."""
import unittest
import subprocess
import sys
from pathlib import Path
from server.enterprises import core
from server.game_server import build_registry

class EnterprisesUnitTests(unittest.TestCase):
    def test_catalog_chain(self):
        recipes=core.catalog().index['recipes']
        self.assertEqual(recipes['field_grain']['outputs']['grain']*10,1000)
        self.assertEqual(recipes['mill_flour']['inputs']['grain'],100)
        self.assertEqual(recipes['mill_flour']['outputs']['flour'],80)
    def test_half_load(self):
        r=core.catalog().index['recipes']['mill_flour']
        self.assertEqual(core.load_bp({'grain':{'quantity':50,'quality':50}},r,4000,10000),5000)
        self.assertEqual(divmod(80*5000,10000),(40,0))
    def test_full_storage(self):
        r=core.catalog().index['recipes']['mill_flour']
        self.assertEqual(core.load_bp({'grain':{'quantity':4000,'quality':50}},r,4000,10000),10000)
        # Milling 100 units of grain frees room for 80 units of flour.
        self.assertEqual(core.load_bp({'grain':{'quantity':50,'quality':50},'flour':{'quantity':3950,'quality':50}},r,4000,10000),5000)
    def test_precision_remainder(self):
        q,rem=divmod(3*3333+1,10000)
        self.assertEqual((q,rem),(1,0))
    def test_strict_integer(self):
        for value in (True,0.5,'10',None):
            with self.assertRaises(ValueError):
                core.integer(value)
    def test_validator_entrypoints(self):
        root=Path(__file__).resolve().parents[2]
        for args in (['tools/validate_enterprises.py'],['-m','tools.validate_enterprises']):
            with self.subTest(args=args):
                result=subprocess.run([sys.executable,*args],cwd=root,capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn('Enterprise catalog validation OK',result.stdout)

    def test_registry(self):
        registry=build_registry()
        self.assertIn(('POST','/enterprises'),registry.routes)
        self.assertIn(('POST','/admin/enterprises/{id}/inventory'),registry.routes)
        self.assertTrue(any(name=='enterprise_production' for _,name,_ in registry.tick_handlers['daily']))
        self.assertTrue(any(name=='enterprise_finances' for _,name,_ in registry.tick_handlers['monthly']))

if __name__=='__main__':
    unittest.main()
