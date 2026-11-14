"""PostgreSQL integration smoke test, isolated rollback transaction for accounts.
The world build test uses a disposable temporary database connection in a transaction
for DB schema checks; no production player records are changed.
"""
import os
import unittest
import uuid
import postgres_db
import auth
import postgres_world

@unittest.skipUnless(os.environ.get("LUNEX_DB_ENGINE")=="postgres","requires isolated PostgreSQL")
class PostgreSQLTests(unittest.TestCase):
    def test_schema_and_read_api(self):
        with postgres_db.connect() as db:
            for table in ("users","sessions","buildings","cells","chunks","events","commands"):
                db.execute("SELECT 1 FROM "+table+" LIMIT 1")
        self.assertEqual(postgres_world.events(0)[0],200)
        self.assertEqual(postgres_world.chunk(0,0)[0],200)

    def test_invalid_auth_and_build(self):
        self.assertEqual(auth.profile("not-a-session")[0],401)
        self.assertEqual(postgres_world.build("test",{"kind":"invalid","x":0,"y":0,"request_id":str(uuid.uuid4())})[0],400)

if __name__=="__main__":
    unittest.main()
