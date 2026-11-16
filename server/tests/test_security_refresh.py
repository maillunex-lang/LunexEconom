"""SEC1: refresh replay revokes a rotated session family."""
import os
import unittest
from uuid import uuid4
from server.game_server import create_app
from server.tests.test_platform_v201 import request

DSN = os.getenv('LUNEX_TEST_DATABASE_URL')

@unittest.skipUnless(DSN, 'Requires isolated PostgreSQL 16')
class RefreshReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = staticmethod(create_app(DSN))

    @classmethod
    def tearDownClass(cls):
        cls.app.close()

    def test_replay_revokes_successor(self):
        name = 'sec' + uuid4().hex[:12]
        data = {'username': name, 'email': name+'@example.test', 'password':'StrongSecurePass123!'}
        self.assertEqual(request(self.app, 'POST', '/auth/register', data, ip='10.131.2.3')[0], 201)
        code, login = request(self.app, 'POST', '/auth/login', {'username':name, 'password':data['password']}, ip='10.131.2.4')
        self.assertEqual(code, 200)
        code, successor = request(self.app, 'POST', '/auth/refresh', {'refresh_token':login['refresh_token']})
        self.assertEqual(code, 200)
        self.assertEqual(request(self.app, 'GET', '/auth/me', token=successor['access_token'])[0], 200)
        self.assertEqual(request(self.app, 'POST', '/auth/refresh', {'refresh_token':login['refresh_token']})[0], 401)
        self.assertEqual(request(self.app, 'GET', '/auth/me', token=successor['access_token'])[0], 401)
