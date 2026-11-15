import unittest
from server.registry import Registry
from server.game_server import build_registry

class TestRegistry(unittest.TestCase):
    def test_unique_routes(self):
        r = Registry()
        r.route('GET','/test',lambda body,ctx:(200,{}))
        with self.assertRaises(ValueError): r.route('GET','/test',lambda body,ctx:None)

    def test_module_contract(self):
        r = build_registry()
        self.assertEqual(len(r.modules),5)
        for path in ('/health','/config','/catalog'):
            self.assertIn(('GET',path),r.routes)
        for path in ('/auth/register','/auth/login'):
            self.assertIn(('POST',path),r.routes)
        self.assertEqual(r.dispatch('GET','/unknown',{},{}), (404,{'error':'not_found'}))
