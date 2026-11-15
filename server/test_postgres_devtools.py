"""Developer tools PostgreSQL integration against disposable CI database only."""
import os
import unittest
import uuid

CI = os.environ.get("LUNEX_DB_ENGINE") == "postgres" and os.environ.get("LUNEX_PG_DB") == "lunex_ci"


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