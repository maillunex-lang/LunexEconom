"""Automatic access road for buildings without road contact (builder pays)."""
import os
import unittest
from uuid import uuid4

from server import db
from server.ledger.api import account, reconcile, transfer
from server.world import core as world
from server.enterprises import core as enterprises

DSN = os.getenv('LUNEX_TEST_DATABASE_URL')
COST = world.AUTO_ROAD_CELL_COST


def _new_player(conn, capital):
    username = 'road' + uuid4().hex[:12]
    actor_id = conn.execute("""INSERT INTO accounts(username,email,password_hash,role)
      VALUES(%s,%s,'test-hash','player') RETURNING id""", (username, username + '@example.test')).fetchone()[0]
    player = account(conn, 'player:' + username, 'player', actor_id)
    transfer(conn, 'road-capital:' + username, account(conn, 'system:treasury'), player, capital)
    return {'id': actor_id, 'username': username}, player


def _find_site(conn, building='field'):
    """A free, unowned parcel position where the building fits but has no road contact."""
    states = world.city_states(conn)
    for px in range(3, 40):
        for py in range(3, 40):
            if conn.execute('SELECT 1 FROM world_parcels WHERE px=%s AND py=%s', (px, py)).fetchone():
                continue
            for x in range(px * 6, px * 6 + 5):
                for y in range(py * 6, py * 6 + 5):
                    ok, reason = world.placement_valid(conn, building, x, y)
                    if ok or reason != 'no_road_access':
                        continue
                    footprint = {(a, b) for a in range(x, x + 2) for b in range(y, y + 2)}
                    if not all(world.cell_zone(a, b, states)[0] == 'free' for a, b in footprint):
                        continue
                    road, _ = world.plan_access_road(conn, 0, footprint)
                    if road and 2 <= len(road) <= world.AUTO_ROAD_MAX_CELLS:
                        return px, py, x, y
    return None


def _give_parcel(conn, px, py, actor):
    conn.execute("""INSERT INTO world_parcels(px,py,city_id,owner_kind,owner_ref,paid_amount)
      VALUES(%s,%s,NULL,'player',%s,10000)""", (px, py, str(actor['id'])))


@unittest.skipUnless(DSN, 'Set LUNEX_TEST_DATABASE_URL to isolated PostgreSQL')
class AutoRoadTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(DSN)
        self.site = _find_site(self.conn)
        self.assertIsNotNone(self.site, 'no site without road contact found')

    def tearDown(self):
        self.conn.rollback()
        self.conn.close()

    def _road_count(self):
        return self.conn.execute('SELECT count(*) FROM world_roads').fetchone()[0]

    def _balance(self, player):
        return self.conn.execute('SELECT balance FROM ledger_accounts WHERE id=%s', (player,)).fetchone()[0]

    def test_road_is_built_and_paid_by_builder(self):
        actor, player = _new_player(self.conn, 1000000)
        px, py, x, y = self.site
        _give_parcel(self.conn, px, py, actor)
        plan_status, plan = enterprises.plan(self.conn, actor, 'field', px, py, x, y)
        self.assertEqual(plan_status, 200)
        self.assertTrue(plan['ok'] and plan['can_afford'])
        cells = plan['road_cells']
        self.assertTrue(2 <= len(cells) <= world.AUTO_ROAD_MAX_CELLS)
        self.assertEqual(plan['road_cost'], len(cells) * COST)
        before_roads, before_balance = self._road_count(), self._balance(player)
        # Preview does not write anything.
        enterprises.plan(self.conn, actor, 'field', px, py, x, y)
        self.assertEqual((self._road_count(), self._balance(player)), (before_roads, before_balance))
        request = 'road-test:' + uuid4().hex
        status, result = enterprises.place(self.conn, actor, request, 'field', px, py, x, y)
        self.assertEqual(status, 201, result)
        self.assertEqual(result['road_cells'], cells)
        self.assertEqual(result['road_cost'], len(cells) * COST)
        self.assertEqual(self._road_count(), before_roads + len(cells))
        self.assertEqual(self._balance(player), before_balance - result['initial_payment'] - len(cells) * COST)
        owners = {r[0] for r in self.conn.execute(
            'SELECT builder_id FROM world_roads WHERE x=%s AND y=%s', tuple(cells[0])).fetchall()}
        self.assertEqual(owners, {actor['id']})
        # The new road starts next to the building and the chain is connected.
        footprint = {(a, b) for a in range(x, x + 2) for b in range(y, y + 2)}
        self.assertTrue(any(abs(cells[0][0] - a) + abs(cells[0][1] - b) == 1 for a, b in footprint))
        self.assertTrue(all(abs(p[0] - q[0]) + abs(p[1] - q[1]) == 1 for p, q in zip(cells, cells[1:])))
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_repeat_request_does_not_charge_or_build_twice(self):
        actor, player = _new_player(self.conn, 1000000)
        px, py, x, y = self.site
        _give_parcel(self.conn, px, py, actor)
        request = 'road-test:' + uuid4().hex
        self.assertEqual(enterprises.place(self.conn, actor, request, 'field', px, py, x, y)[0], 201)
        roads, balance = self._road_count(), self._balance(player)
        status, result = enterprises.place(self.conn, actor, request, 'field', px, py, x, y)
        self.assertEqual(status, 200)
        self.assertTrue(result['idempotent'])
        self.assertEqual((self._road_count(), self._balance(player)), (roads, balance))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM ledger_transfers WHERE request_id=%s',
                                           ('enterprise:road:' + request,)).fetchone()[0], 1)

    def test_insufficient_funds_changes_nothing(self):
        actor, player = _new_player(self.conn, 12000)  # covers the 11700 first stage but not the road
        px, py, x, y = self.site
        _give_parcel(self.conn, px, py, actor)
        roads, balance = self._road_count(), self._balance(player)
        status, result = enterprises.place(self.conn, actor, 'road-test:' + uuid4().hex, 'field', px, py, x, y)
        self.assertEqual(status, 409)
        self.assertEqual(result['error'], 'insufficient_funds')
        self.assertGreater(result['road_cost'], 0)
        self.assertEqual(result['shortfall'], result['required'] - balance)
        self.assertEqual((self._road_count(), self._balance(player)), (roads, balance))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM enterprises WHERE owner_id=%s',
                                           (actor['id'],)).fetchone()[0], 0)
        self.assertFalse(enterprises.plan(self.conn, actor, 'field', px, py, x, y)[1]['can_afford'])

    def test_path_is_deterministic_and_avoids_foreign_parcels(self):
        actor, _ = _new_player(self.conn, 1000000)
        px, py, x, y = self.site
        footprint = {(a, b) for a in range(x, x + 2) for b in range(y, y + 2)}
        first, _ = world.plan_access_road(self.conn, actor['id'], footprint)
        again, _ = world.plan_access_road(self.conn, actor['id'], footprint)
        self.assertEqual(first, again)
        # Hand the parcel of the first path cell outside the building parcel to a stranger.
        stranger, _ = _new_player(self.conn, 1)
        outside = [c for c in first if (c[0] // 6, c[1] // 6) != (px, py)]
        if outside:
            fx, fy = outside[0][0] // 6, outside[0][1] // 6
            self.conn.execute("""INSERT INTO world_parcels(px,py,city_id,owner_kind,owner_ref,paid_amount)
              VALUES(%s,%s,NULL,'player',%s,1) ON CONFLICT DO NOTHING""", (fx, fy, str(stranger['id'])))
            detour, reason = world.plan_access_road(self.conn, actor['id'], footprint)
            if detour is not None:
                self.assertFalse(any((c[0] // 6, c[1] // 6) == (fx, fy) for c in detour))
            else:
                self.assertEqual(reason, 'road_unreachable')

    def test_far_site_is_rejected_without_changes(self):
        actor, player = _new_player(self.conn, 1000000)
        # Far outside every city and every road.
        px, py = 5000, 5000
        _give_parcel(self.conn, px, py, actor)
        roads, balance = self._road_count(), self._balance(player)
        status, result = enterprises.place(self.conn, actor, 'road-test:' + uuid4().hex, 'field',
                                           px, py, px * 6, py * 6)
        self.assertEqual(status, 409)
        self.assertEqual(result['error'], 'road_unreachable')
        self.assertEqual((self._road_count(), self._balance(player)), (roads, balance))
        self.assertFalse(enterprises.plan(self.conn, actor, 'field', px, py, px * 6, py * 6)[1]['ok'])


if __name__ == '__main__':
    unittest.main()
