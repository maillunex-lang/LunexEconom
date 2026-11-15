"""Developer tools PostgreSQL integration against disposable CI database only."""
import os
import unittest
import uuid

CI = os.environ.get("LUNEX_DB_ENGINE") == "postgres" and os.environ.get("LUNEX_PG_DB") == "lunex_ci"


class SavepointConnection:
    """Suppress application-level commits inside a rollback-only CI savepoint."""
    def __init__(self, db):
        self.db = db

    def execute(self, *args, **kwargs):
        return self.db.execute(*args, **kwargs)

    def commit(self):
        pass


@unittest.skipUnless(CI, "requires isolated lunex_ci PostgreSQL")
class DeveloperPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import postgres_db
        # Initialize once, outside the test transaction; init opens its own connection.
        postgres_db.init()

    def test_schema_and_terrain_events(self):
        import postgres_db
        import devtools
        with postgres_db.connect() as db:
            devtools.ensure(db, "%s", postgres=True)
            db.execute("SAVEPOINT devtools_ci")
            try:
                cx, cy = 833, 833
                devtools.publish_terrain_events(db, "%s", [(cx * 12, cy * 12)])
                version = db.execute("SELECT version FROM chunks WHERE cx=%s AND cy=%s", (cx, cy)).fetchone()
                self.assertIsNotNone(version)
                event = db.execute("SELECT kind FROM events WHERE cx=%s AND cy=%s ORDER BY seq DESC LIMIT 1", (cx, cy)).fetchone()
                self.assertEqual(event[0], "terrain_changed")
            finally:
                db.execute("ROLLBACK TO SAVEPOINT devtools_ci")
                db.execute("RELEASE SAVEPOINT devtools_ci")

    def test_developer_city_creation_and_undo(self):
        import postgres_db
        import devtools
        from unittest.mock import patch
        with postgres_db.connect() as db:
            devtools.ensure(db, "%s", postgres=True)
            db.execute("SAVEPOINT devtools_ci_create")
            try:
                # Locate a valid urban 2x2 patch dynamically. The CI
                # database can have different generated city boundaries.
                import geo
                import roads
                import zoning
                payload = None
                for city in geo.cities():
                    cx, cy = int(city["x"]), int(city["y"])
                    for dx in range(-12, 13):
                        for dy in range(-12, 13):
                            x, y = cx + dx, cy + dy
                            cells = [(x+i, y+j) for i in range(2) for j in range(2)]
                            if any(roads.is_base_road(a,b) or roads.is_water(a,b) for a,b in cells):
                                continue
                            if any(db.execute("SELECT 1 FROM cells WHERE x=%s AND y=%s", (a,b)).fetchone() for a,b in cells):
                                continue
                            if zoning.check(db, "%s", "park", cells):
                                continue
                            payload = {"request_id": str(uuid.uuid4()), "kind": "park", "x": x, "y": y}
                            break
                        if payload:
                            break
                    if payload:
                        break
                self.assertIsNotNone(payload, "No urban test site available")
                before = db.execute("SELECT COUNT(*) FROM ledger_tx").fetchone()[0]
                isolated = SavepointConnection(db)
                with patch("devtools.require_developer", return_value=True):
                    status, result = devtools.building_create(isolated, "%s", "ci_operator", payload, "ci")
                    self.assertEqual(status, 200, result)
                    oid = result["object_id"]
                    import economy
                    self.assertEqual(db.execute("SELECT owner FROM buildings WHERE id=%s", (oid,)).fetchone()[0], economy.CITY)
                    self.assertEqual(devtools.building_create(isolated, "%s", "ci_operator", payload, "ci")[1]["replayed"], True)
                    status, result = devtools.undo(isolated, "%s", "ci_operator", {"request_id": str(uuid.uuid4())}, "ci")
                    self.assertEqual(status, 200, result)
                    self.assertIsNone(db.execute("SELECT id FROM buildings WHERE id=%s", (oid,)).fetchone())
                self.assertEqual(db.execute("SELECT COUNT(*) FROM ledger_tx").fetchone()[0], before)
            finally:
                db.execute("ROLLBACK TO SAVEPOINT devtools_ci_create")
                db.execute("RELEASE SAVEPOINT devtools_ci_create")