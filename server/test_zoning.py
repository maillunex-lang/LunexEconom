"""City zones, production zones and dynamic city growth (docs/ZONING.md)."""
import math
import os
import tempfile
import unittest
import uuid
from unittest import mock

import auth
import citygen
import economy
import game_server
import geo
import zoning

NOW = 1_800_000_000


class ZoneGeometryTests(unittest.TestCase):
    def test_a_city_has_a_centre_a_suburb_an_industrial_wedge_and_open_land(self):
        city = geo.get_city("ufa")
        cx, cy, r = city["x"], city["y"], city["radius"]
        self.assertEqual(zoning.zone_of("ufa", cx, cy, r, 0, cx, cy), "center")
        angle = math.radians(zoning.wedge_angle("ufa"))
        mid = r * 0.7
        self.assertEqual(zoning.zone_of("ufa", cx, cy, r, 0, round(cx + mid * math.cos(angle)), round(cy + mid * math.sin(angle))), "industrial")
        opposite = angle + math.pi
        self.assertEqual(zoning.zone_of("ufa", cx, cy, r, 0, round(cx + mid * math.cos(opposite)), round(cy + mid * math.sin(opposite))), "suburb")
        self.assertEqual(zoning.zone_of("ufa", cx, cy, r, 0, cx + r + 5, cy), "open")

    def test_the_industrial_wedge_never_reaches_the_centre(self):
        city = geo.get_city("ufa")
        for x in range(-40, 41):
            for y in range(-40, 41):
                if math.hypot(x, y) <= city["radius"] * zoning.CORE_SHARE:
                    self.assertNotEqual(zoning.zone_of("ufa", 0, 0, city["radius"], 0, x, y), "industrial")

    def test_the_radius_grows_with_the_level(self):
        self.assertEqual(zoning.effective_radius(60, 0), 60)
        self.assertEqual(zoning.effective_radius(60, 2), 90)

    def test_factories_need_the_industrial_zone_and_houses_the_city(self):
        self.assertEqual(zoning.ALLOWED["factory"], ("industrial",))
        self.assertNotIn("industrial", zoning.ALLOWED["house"])
        self.assertNotIn("center", zoning.ALLOWED["factory"])
        self.assertNotIn("center", zoning.ALLOWED["mine"])
        self.assertNotIn("center", zoning.ALLOWED["farm"])


class ZoneWorldTests(unittest.TestCase):
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

    def rich(self, who="alice"):
        game_server.wallet(who)
        with game_server.connect() as db:
            db.execute("UPDATE wallets SET balance=50000000 WHERE account=?", (economy.player_account(who),))

    def generate(self, ids=("ufa",)):
        with game_server.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            citygen.seed(db, "?", list(ids), NOW)
            db.commit()

    def build(self, kind, x, y, who="alice"):
        return game_server.build(who, {"kind": kind, "x": x, "y": y, "request_id": str(uuid.uuid4())})

    def wedge_cell(self, fraction=0.7):
        city = geo.get_city("ufa")
        angle = math.radians(zoning.wedge_angle("ufa"))
        return round(city["radius"] * fraction * math.cos(angle)), round(city["radius"] * fraction * math.sin(angle))

    def test_no_zones_before_the_cities_are_generated(self):
        self.rich()
        self.assertFalse(zoning.overview(*self._db())["enabled"])
        self.assertEqual(self.build("factory", 1, 1)[0], 201)            # the empty world has no zones

    def _db(self):
        db = game_server.connect()
        self.addCleanup(db.close)
        return db, "?"

    def free_centre_spot(self, w=3, h=3):
        with game_server.connect() as db:
            taken = {(x, y) for x, y in db.execute("SELECT x,y FROM cells").fetchall()} | {(x, y) for x, y in db.execute("SELECT x,y FROM roads").fetchall()}
        import roads
        for x in range(-14, 15):
            for y in range(-14, 15):
                cells = [(x + i, y + j) for i in range(w) for j in range(h)]
                if not any(c in taken or roads.is_base_road(*c) for c in cells) and all(zoning.zone_at(a, b, {}) == "center" for a, b in cells):
                    return x, y
        self.fail("no free spot in the centre")

    def test_a_factory_in_the_city_centre_is_refused_after_generation(self):
        self.generate()
        self.rich()
        x, y = self.free_centre_spot()
        for kind in ("factory", "mine", "farm", "warehouse"):
            status, body = self.build(kind, x, y)
            self.assertEqual((status, body.get("error"), body.get("zone")), (409, "wrong_zone", "center"), (kind, body))
            self.assertEqual(body["zone_name"], "центр города")
        status, body = self.build("shop", x, y)
        self.assertNotEqual(body.get("error"), "wrong_zone")              # shops belong to the city

    def test_a_factory_is_allowed_in_the_industrial_zone(self):
        self.generate()
        self.rich()
        x, y = self.wedge_cell()
        with game_server.connect() as db:
            self.assertIsNone(zoning.check(db, "?", "factory", [(x + i, y + j) for i in range(3) for j in range(2)]))
        status, body = self.build("factory", x, y)
        self.assertIn(body.get("error"), (None, "no_road_access", "water"), body)     # the zone does not refuse it
        self.assertNotEqual(body.get("error"), "wrong_zone")

    def test_a_house_never_stands_in_the_industrial_zone(self):
        self.generate()
        with game_server.connect() as db:
            for x, y in db.execute("SELECT c.x,c.y FROM cells c JOIN buildings b ON b.id=c.object_id WHERE b.kind='house'").fetchall():
                self.assertIn(zoning.zone_at(x, y, {}), zoning.CITY_ZONES)

    def test_a_filling_city_grows_and_keeps_free_land(self):
        self.generate()
        city = geo.get_city("ufa")
        with game_server.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            before = zoning.overview(db, "?")["cities"][0]
            self.assertEqual((before["level"], before["radius"]), (0, city["radius"]))
            self.assertEqual(zoning.expand_cities(db, "?", NOW), {})        # a young city is not crowded
            for x in range(-city["radius"], city["radius"] + 1):            # build the whole city land over (roads count as built-over land)
                for y in range(-city["radius"], city["radius"] + 1):
                    if math.hypot(x, y) < city["radius"] and zoning.zone_at(x, y, {}) in zoning.CITY_ZONES:
                        db.execute("INSERT OR IGNORE INTO roads(x,y,owner,created) VALUES(?,?,?,?)", (x, y, "alice", NOW))
            self.assertEqual(zoning.expand_cities(db, "?", NOW), {"ufa": 1})
            after = zoning.overview(db, "?")["cities"][0]
            self.assertEqual((after["level"], after["radius"]), (1, zoning.effective_radius(city["radius"], 1)))
            for _ in range(zoning.MAX_LEVEL + 1):                           # a city that stays crowded keeps growing, one level a month, up to the limit
                if not zoning.expand_cities(db, "?", NOW):
                    break
            top = zoning.overview(db, "?")["cities"][0]["level"]
            self.assertTrue(1 <= top <= zoning.MAX_LEVEL)
            self.assertEqual(zoning.expand_cities(db, "?", NOW).get("ufa", top), top)
            db.commit()
        # the growth turns up free urban land for new houses
        self.assertGreater(len(citygen._candidates("ufa", 1, 1, 1)), len(citygen._candidates("ufa", 1, 1, 0)))

    def test_growth_extends_the_zones_and_the_house_lots(self):
        small = citygen._candidates("ufa", 1, 1, 0)
        grown = citygen._candidates("ufa", 1, 1, 2)
        self.assertGreater(len(grown), len(small))

    def test_zone_endpoint_and_the_mirror_in_the_client(self):
        self.generate()
        with game_server.connect() as db:
            view = zoning.overview(db, "?")
        self.assertTrue(view["enabled"])
        self.assertEqual(len(view["cities"]), 20)
        self.assertIn("factory", view["allowed"])
        text = open(os.path.join(os.path.dirname(__file__), "..", "client", "zones.gd"), encoding="utf-8").read()
        for name, value in (("CORE_SHARE", zoning.CORE_SHARE), ("WEDGE_DEGREES", zoning.WEDGE_DEGREES), ("EXPAND_STEP", zoning.EXPAND_STEP)):
            self.assertIn("const %s := %s" % (name, value), text)


def zoning_limit(city):
    return int(city["radius"]) + 2


if __name__ == "__main__":
    unittest.main()
