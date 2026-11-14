"""Initial city generation: plan properties, real houses in the world, idempotence, growth, isolation from the economy."""
import json
import os
import tempfile
import unittest
from unittest import mock

import auth
import citygen
import economy
import game_server
import geo
import production
import roads

NOW = 1_800_000_000


class PlanTests(unittest.TestCase):
    def test_every_city_has_a_plan_that_covers_its_target(self):
        for city in geo.cities():
            lots = citygen.plan(city["id"])
            self.assertGreaterEqual(len(lots), citygen.target_houses(city, 200), city["id"])

    def test_plan_is_deterministic_and_lots_are_valid(self):
        for city in geo.cities():
            first = citygen.plan(city["id"])
            citygen._plan.cache_clear()
            self.assertEqual(first, citygen.plan(city["id"]), city["id"])
            seen = set()
            for x, y in first:
                cells = [(x + i, y + j) for i in range(2) for j in range(2)]
                self.assertFalse(set(cells) & seen, "lots overlap")
                seen |= set(cells)
                for c in cells:
                    self.assertEqual(citygen.terrain(*c), "grass", (city["id"], c))
                    self.assertFalse(roads.is_water(*c) or roads.is_base_road(*c))
                    self.assertFalse(citygen.is_street(city, *c) or citygen.is_square(city, *c))
                    self.assertLessEqual(((c[0] - city["x"]) ** 2 + (c[1] - city["y"]) ** 2) ** 0.5, city["radius"])

    def test_the_start_area_of_the_game_city_stays_free_for_players(self):
        city = geo.get_city("ufa")
        for x, y in citygen.plan("ufa"):
            self.assertGreaterEqual(((x + 1 - city["x"]) ** 2 + (y + 1 - city["y"]) ** 2) ** 0.5, citygen.INNER_FREE_GAME_CITY - 1)

    def test_houses_stand_along_streets(self):
        city = geo.get_city("sterlitamak")
        for x, y in citygen.plan("sterlitamak"):
            ring = [(x + i, y + j) for i in range(-1, 3) for j in range(-1, 3) if not (0 <= i < 2 and 0 <= j < 2)]
            self.assertTrue(any(citygen.is_street(city, *c) for c in ring))

    def test_house_ids_are_stable_and_unique(self):
        ids = {citygen.house_id("ufa", x, y) for x, y in citygen.plan("ufa")}
        self.assertEqual(len(ids), len(citygen.plan("ufa")))
        self.assertEqual(citygen.house_id("ufa", 5, 6), citygen.house_id("ufa", 5, 6))


class WorldBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [mock.patch.object(game_server, "DB", os.path.join(self.tmp.name, "world.sqlite3")),
                        mock.patch.object(auth, "DB_PATH", os.path.join(self.tmp.name, "accounts.sqlite3"))]
        for p in self.patches:
            p.start()
        with game_server.connect() as db:
            db.execute("INSERT INTO world_clock VALUES(1,1800000000,86400,0)")

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def seed(self, ids="all", dry=False):
        with game_server.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            result = citygen.seed(db, "?", ids, NOW, dry_run=dry)
            db.commit()
        return result

    def scalar(self, sql, params=()):
        with game_server.connect() as db:
            return db.execute(sql, params).fetchone()[0]

    def snapshot(self, *tables):
        with game_server.connect() as db:
            return {t: db.execute("SELECT * FROM " + t + " ORDER BY 1,2").fetchall() for t in tables}


class SeedTests(WorldBase):
    def test_dry_run_writes_nothing(self):
        before = self.snapshot("buildings", "cells", "events", "chunks")
        result = self.seed(dry=True)
        self.assertGreater(sum(r["placed"] for r in result), 100)
        self.assertEqual(before, self.snapshot("buildings", "cells", "events", "chunks"))

    def test_all_cities_get_their_houses_as_real_buildings(self):
        result = self.seed()
        self.assertEqual(len(result), 20)
        for r in result:
            self.assertEqual(r["placed"], min(r["target"], r["plan_size"]), r["city_id"])
            owner = citygen.owner_of(r["city_id"])
            self.assertEqual(self.scalar("SELECT COUNT(*) FROM buildings WHERE owner=? AND kind='house'", (owner,)), r["placed"])
        houses = self.scalar("SELECT COUNT(*) FROM buildings WHERE kind='house'")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM cells"), houses * 4)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM events WHERE kind='building_created'") >= houses, True)
        with game_server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM cells c LEFT JOIN buildings b ON b.id=c.object_id WHERE b.id IS NULL").fetchone()[0], 0)
            versions = dict(db.execute("SELECT cx,cy FROM chunks").fetchall())
            self.assertTrue(versions)

    def test_running_it_twice_creates_nothing_new(self):
        self.seed()
        first = self.snapshot("buildings", "cells", "events", "chunks")
        second = self.seed()
        self.assertEqual(sum(r["placed"] for r in second), 0)
        self.assertEqual(first, self.snapshot("buildings", "cells", "events", "chunks"))

    def test_the_economy_is_untouched(self):
        before = self.snapshot("wallets", "ledger_tx", "ledger_entries", "building_ops", "loans", "company_status")
        self.seed()
        self.assertEqual(before, self.snapshot("wallets", "ledger_tx", "ledger_entries", "building_ops", "loans", "company_status"))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM building_ops"), 0)         # houses have no jobs, upkeep or taxes

    def test_player_buildings_and_roads_are_never_overwritten(self):
        lot = citygen.plan("ufa")[0]
        with game_server.connect() as db:
            db.execute("INSERT INTO buildings VALUES('mine1','alice','farm',?,?,?)", (lot[0], lot[1], NOW))
            db.execute("INSERT INTO cells VALUES(?,?,'mine1')", lot)
            second = citygen.plan("ufa")[1]
            db.execute("INSERT INTO roads VALUES(?,?,'alice',?)", (second[0] + 1, second[1] + 1, NOW))
        self.seed(["ufa"])
        self.assertEqual(self.scalar("SELECT owner FROM buildings WHERE id='mine1'"), "alice")
        self.assertEqual(self.scalar("SELECT object_id FROM cells WHERE x=? AND y=?", lot), "mine1")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM cells c JOIN buildings b ON b.id=c.object_id WHERE b.owner='town:ufa' AND c.x=? AND c.y=?", (second[0] + 1, second[1] + 1)), 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM buildings WHERE owner='town:ufa'"), citygen.target_houses(geo.get_city("ufa"), 200))

    def test_players_cannot_build_or_sell_houses(self):
        self.seed(["ufa"])
        self.assertEqual(game_server.build("alice", {"kind": "house", "x": 40, "y": 40, "request_id": "00000000-0000-4000-8000-000000000001"})[0], 400)
        object_id = self.scalar("SELECT id FROM buildings WHERE owner='town:ufa' LIMIT 1")
        status, data = game_server.sell("alice", {"object_id": object_id, "request_id": "00000000-0000-4000-8000-000000000002"})
        self.assertEqual((status, data["error"]), (403, "not_owner"))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM buildings WHERE id=?", (object_id,)), 1)

    def test_clients_receive_the_houses_in_chunk_snapshots_and_events(self):
        self.seed(["ufa"])
        x, y = citygen.plan("ufa")[0]
        status, data = game_server.chunk(x // 12, y // 12)
        self.assertEqual(status, 200)
        kinds = {(c["x"], c["y"]): (c["building_kind"], c["owner"]) for c in data["cells"] if c["kind"] == "building_created"}
        self.assertEqual(kinds[(x, y)], ("house", "town:ufa"))
        status, ev = game_server.events(0)
        self.assertTrue(any(e.get("building_kind") == "house" for e in ev["events"]))

    def test_town_owners_can_never_collide_with_a_player_name(self):
        code, data = auth.register({"username": "town:ufa", "email": "t@example.test", "password": "safe-password-1"}, "x")
        self.assertEqual((code, data.get("error")), (400, "invalid_username"))

    def test_unknown_city_is_refused(self):
        with self.assertRaises(ValueError):
            self.seed(["atlantis"])


class GrowthTests(WorldBase):
    def months(self, n):
        with game_server.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for m in range(n):
                production.step_month(db, "?", m, NOW + m)
            db.commit()

    def houses(self):
        return self.scalar("SELECT COUNT(*) FROM buildings WHERE owner='town:ufa'")

    def test_nothing_grows_before_the_city_was_generated(self):
        self.months(3)
        self.assertEqual(self.houses(), 0)

    def test_houses_follow_the_population_after_generation(self):
        self.seed(["ufa"])
        start = self.houses()
        self.assertEqual(start, 25)                                   # 200 residents / 8 per house
        with game_server.connect() as db:
            db.execute("DELETE FROM population")
            db.execute("INSERT INTO population VALUES(0,200,100,0,1500,1000,1000,600)")        # 600 residents next month -> 75 houses
        self.months(1)
        self.assertEqual(self.houses(), start + citygen.GROW_PER_MONTH)   # at most a few per month
        self.months(2)
        self.assertGreater(self.houses(), start + citygen.GROW_PER_MONTH)
        self.assertLessEqual(self.houses(), 75)

    def test_a_shrinking_population_never_removes_houses(self):
        self.seed(["ufa"])
        start = self.houses()
        with game_server.connect() as db:
            db.execute("DELETE FROM population")
            db.execute("INSERT INTO population VALUES(0,200,100,0,1500,1000,1000,140)")
        self.months(2)
        self.assertGreaterEqual(self.houses(), start)

    def test_ledger_stays_balanced_through_the_monthly_step_with_houses(self):
        self.seed(["ufa"])
        self.months(3)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM (SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0) x"), 0)


if __name__ == "__main__":
    unittest.main()
