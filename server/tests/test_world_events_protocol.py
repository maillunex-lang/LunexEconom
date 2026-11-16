"""MAP-RT1: pure protocol guardrails; PostgreSQL tests use isolated database only."""
import unittest
from server.world import api


class WorldEventProtocolTests(unittest.TestCase):
    def test_chunk_filter_rejects_untrusted_queries(self):
        good={'query':{'chunks':['-1,0;2,3']}}
        self.assertEqual(api._subscribe_chunks(good),[(-1,0),(2,3)])
        for bad in ('nan,2','1,2;','1,2;1,2','1,2,3','1,2;select *',
                    '1,2;'*96+'3,4','9999999999999999999,2'):
            with self.subTest(value=bad),self.assertRaises(ValueError):
                api._subscribe_chunks({'query':{'chunks':[bad]}})

    def test_short_poll_cap_and_rate(self):
        import uuid
        ip='10.67.0.'+str(int(uuid.uuid4().hex[:2],16))
        account=uuid.uuid4().hex
        for _ in range(90):
            self.assertEqual(api._admit(account,ip),(True,None))
        self.assertEqual(api._admit(account,ip),(False,'rate'))

    def test_flags_are_safe(self):
        from server.game_server import build_registry
        flags=build_registry().flags
        self.assertFalse(flags['world_events_wait_enabled'])
        self.assertFalse(flags['world_events_retention_enabled'])
        self.assertEqual(flags['world_events_waiter_cap'],12)
