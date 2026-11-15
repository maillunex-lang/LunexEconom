"""Four-stage construction, municipal tenders and balanced accounts on
disposable PostgreSQL 'lunex_ci'. Each class uses its own drop-on-exit schema.
"""
import os
import unittest
import uuid
from unittest import mock

CI=os.environ.get("LUNEX_DB_ENGINE")=="postgres" and os.environ.get("LUNEX_PG_DB")=="lunex_ci"
if CI:
    import construction_projects as projects
    import contractors
    import economy
    import goods_catalog
    import land
    import postgres_db
    import city
    import tenders

NOW=1_800_000_000

def rid(): return str(uuid.uuid4())

@unittest.skipUnless(CI,"requires isolated lunex_ci PostgreSQL")
class ConstructionPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema="ex_construction_"+uuid.uuid4().hex[:12]
        cls.original_connect=postgres_db.connect
        with cls.original_connect() as db:
            db.execute(f"CREATE SCHEMA {cls.schema}")
        def isolated_connection():
            db=cls.original_connect()
            db.execute(f"SET search_path TO {cls.schema}")
            return db
        cls.patcher=mock.patch.object(postgres_db,"connect",side_effect=isolated_connection)
        cls.patcher.start()
        try:
            postgres_db.init()
        except BaseException:
            cls.patcher.stop()
            with cls.original_connect() as db:db.execute(f"DROP SCHEMA {cls.schema} CASCADE")
            raise

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()
        with cls.original_connect() as db:
            db.execute(f"DROP SCHEMA {cls.schema} CASCADE")

    def setUp(self):
        with postgres_db.connect() as db:
            tables=[r[0] for r in db.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema()").fetchall()]
            db.execute("TRUNCATE TABLE "+",".join(tables)+" RESTART IDENTITY CASCADE")
            contractors.ensure(db,"%s")

    def cmd(self,fn,owner,payload,now=NOW):
        with postgres_db.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(20261114)")
            return fn(db,"%s",owner,payload,now)

    def test_project_commissioning_materials_and_balance(self):
        with mock.patch.dict(os.environ,{"LAND_ENABLED":"1","CONSTRUCTION_PROJECTS_ENABLED":"1"}):
            with postgres_db.connect() as db:
                db.execute("SELECT pg_advisory_xact_lock(20261114)")
                economy.ensure_wallet(db,"%s","alice",NOW)
                economy.post(db,"%s","test_grant","isolated PG balance",
                    [(economy.player_account("alice"),12_000_000),(economy.TREASURY,-12_000_000)],NOW)
                for g in goods_catalog.GOODS:
                    db.execute("""INSERT INTO market_prices(product,month_index,price,supply,demand)
                               VALUES(%s,%s,%s,%s,%s)""",(g.id,0,g.reference_price,10_000,100))
            purchased=self.cmd(land.buy,"alice",{"px":0,"py":0,"request_id":rid()})
            self.assertEqual(purchased[0],201,purchased)
            created=self.cmd(projects.create,"alice",{"object_id":"house_wood","x":1,"y":1,"request_id":rid()})
            self.assertEqual(created[0],201,created)
            pid=created[1]["project_id"]
            with postgres_db.connect() as db:
                db.execute("SELECT pg_advisory_xact_lock(20261114)")
                self.assertEqual(projects.monthly(db,"%s",1,NOW+86400)["completed"],1)
                self.assertEqual(projects.monthly(db,"%s",1,NOW+86400)["completed"],0)
            with postgres_db.connect() as db:
                self.assertEqual(db.execute("SELECT stage_index FROM construction_projects WHERE id=%s",(pid,)).fetchone()[0],4)
                self.assertEqual(db.execute("SELECT capacity FROM construction_housing_supply WHERE project_id=%s",(pid,)).fetchone()[0],4)
                self.assertEqual(db.execute("SELECT SUM(balance) FROM wallets").fetchone()[0],0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM (SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0) z").fetchone()[0],0)

    def test_tender_with_npc_and_no_double_city_spend(self):
        with mock.patch.dict(os.environ,{"LAND_ENABLED":"1","CONSTRUCTION_PROJECTS_ENABLED":"1"}):
            with postgres_db.connect() as db:
                db.execute("SELECT pg_advisory_xact_lock(20261114)")
                city.set_mayor(db,"%s","mayor","Mayor",0,now=NOW)
                economy.ensure_wallet(db,"%s",economy.CITY,NOW)
                economy.post(db,"%s","test_grant","isolated PG city",
                             [(economy.player_account(economy.CITY),50_000_000),
                              (economy.TREASURY,-50_000_000)],NOW)
            created=self.cmd(tenders.create,"mayor",
                      {"object_id":"bus_stop","x":1,"y":2,"request_id":rid()})
            self.assertEqual(created[0],201,created)
            with postgres_db.connect() as db:
                state=db.execute("SELECT status,winner FROM tenders WHERE id=%s",
                               (created[1]["tender_id"],)).fetchone()
                self.assertEqual(state[0],"awarded")
                self.assertTrue(state[1].startswith("npc:"))
                self.assertEqual(db.execute("SELECT COUNT(*) FROM ledger_tx WHERE kind='construction_reserve'").fetchone()[0],1)
                self.assertEqual(db.execute("SELECT SUM(balance) FROM wallets").fetchone()[0],0)
