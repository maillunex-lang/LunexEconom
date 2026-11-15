"""PostgreSQL runtime configuration tests, deliberately gated to lunex_ci."""
import os
import unittest

ENABLED = os.environ.get("LUNEX_DB_ENGINE") == "postgres" and os.environ.get("LUNEX_PG_DB") == "lunex_ci"
if ENABLED:
    import postgres_db
    import admin_api
    import runtime_config
    import presence
    import live_config_api

@unittest.skipUnless(ENABLED, "requires disposable lunex_ci")
class PostgresRuntimeConfigTests(unittest.TestCase):
    def setUp(self):
        postgres_db.init()
    def test_revision_and_month_boundary(self):
        with postgres_db.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(20261114)")
            db.execute("DELETE FROM runtime_config_values")
            db.execute("DELETE FROM runtime_config_revisions")
            db.execute("UPDATE runtime_config_state SET revision=0 WHERE id=1")
            result = runtime_config.change(db,"%s",{"HOUSEHOLDS_ENABLED":True},
                      "pg-test","-",1000,confirmed=True)
            self.assertEqual(result["revision"],1)
            month=result["values"]["HOUSEHOLDS_ENABLED"]["apply_month"]
            self.assertFalse(runtime_config.values(db,month-1).get("HOUSEHOLDS_ENABLED",False))
            self.assertTrue(runtime_config.values(db,month).get("HOUSEHOLDS_ENABLED"))
            restored=runtime_config.rollback(db,"%s",1,"pg-test","-",1000,confirmed=True)
            self.assertEqual(restored["revision"],2)
    def test_presence_upsert(self):
        with postgres_db.connect() as db:
            now=1880000000
            self.assertTrue(presence.touch(db,"%s","chatgpt13_ci","1","ufa",now))
            self.assertFalse(presence.touch(db,"%s","chatgpt13_ci","1","ufa",now+5))
            self.assertGreaterEqual(presence.summary(db,"%s",now+10)["online"],1)

if __name__=="__main__": unittest.main()
