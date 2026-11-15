"""City zones and growth on the disposable PostgreSQL 16 database lunex_ci (docs/ZONING.md)."""
import math
import os
import unittest
import uuid
from unittest import mock

ENABLED = os.environ.get("LUNEX_DB_ENGINE") == "postgres" and os.environ.get("LUNEX_PG_DB") == "lunex_ci"

if ENABLED:
    import citygen
    import economy
    import game_server
    import geo
    import postgres_db
    import postgres_world
    import zoning

NOW = 1_800_000_000


@unittest.skipUnless(ENABLED, "requires isolated lunex_ci PostgreSQL database")
class PostgresZoningTests(unittest.TestCase):
    def setUp(self):
        postgres_db.init()
        with postgres_db.connect() as db:
            names = [r[0] for r in db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()]
            keep = {"users", "sessions", "auth_attempts", "auth_tokens", "email_verified", "schema_migrations"}
            db.execute("TRUNCATE TABLE " + ",".join(sorted(n for n in names if n not in keep)) + " RESTART IDENTITY CASCADE")
        p = mock.patch.object(game_server.time, "time", side_effect=lambda: NOW)
        p.start()
        self.addCleanup(p.stop)

    def test_zones_refuse_a_factory_in_the_centre_and_cities_grow(self):
        with postgres_db.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(20261114)")
            citygen.seed(db, "%s", ["ufa"], NOW)
        postgres_world.wallet("alice")
        with postgres_db.connect() as db:
            db.execute("UPDATE wallets SET balance=50000000 WHERE account=%s", (economy.player_account("alice"),))
            taken = {(x, y) for x, y in db.execute("SELECT x,y FROM cells").fetchall()}
        spot = next((x, y) for x in range(-14, 12) for y in range(-14, 12)
                    if not any((x + i, y + j) in taken or abs(x + i) <= 4 and (y + j) == 0 or abs(y + j) <= 4 and (x + i) == 0 for i in range(3) for j in range(3))
                    and all(zoning.zone_at(x + i, y + j, {}) == "center" for i in range(3) for j in range(3)))
        status, body = postgres_world.build("alice", {"kind": "factory", "x": spot[0], "y": spot[1], "request_id": str(uuid.uuid4())})
        self.assertEqual((status, body.get("error"), body.get("zone")), (409, "wrong_zone", "center"))
        city = geo.get_city("ufa")
        with postgres_db.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(20261114)")
            for x in range(-city["radius"], city["radius"] + 1):
                for y in range(-city["radius"], city["radius"] + 1):
                    if math.hypot(x, y) < city["radius"] and zoning.zone_at(x, y, {}) in zoning.CITY_ZONES:
                        db.execute("INSERT INTO roads(x,y,owner,created) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING", (x, y, "alice", NOW))
            grown = zoning.expand_cities(db, "%s", NOW)
            view = zoning.overview(db, "%s")
        self.assertEqual(grown.get("ufa"), 1)
        self.assertGreater(view["cities"][0]["radius"], city["radius"])


if __name__ == "__main__":
    unittest.main()
