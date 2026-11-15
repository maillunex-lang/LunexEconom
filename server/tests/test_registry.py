import unittest
from server.registry import Registry
from server.game_server import build_registry

class TestRegistry(unittest.TestCase):
    def test_unique_routes(self):
        r = Registry()
        r.route('GET','/test',lambda body,ctx:(200,{}))
        with self.assertRaises(ValueError): r.route('GET','/test',lambda body,ctx:None)

    def test_named_ordered_ticks(self):
        r = Registry()
        r.tick('daily','second',lambda conn,idx:None,order=20)
        r.tick('daily','first',lambda conn,idx:None,order=10)
        self.assertEqual([entry[1] for entry in sorted(r.tick_handlers['daily'])],['first','second'])
        with self.assertRaises(ValueError):
            r.tick('daily','first',lambda conn,idx:None,order=30)
        with self.assertRaises(ValueError):
            r.tick('other','x',lambda conn,idx:None)

    def test_module_contract(self):
        r = build_registry()
        self.assertEqual(len(r.modules),8)
        self.assertIn('server.enterprises', [module.__name__ for module in r.modules])
        for path in ('/health','/config','/catalog'):
            self.assertIn(('GET',path),r.routes)
        for path in ('/auth/register','/auth/login'):
            self.assertIn(('POST',path),r.routes)
        self.assertEqual(r.dispatch('GET','/unknown',{},{}), (404,{'error':'not_found'}))
