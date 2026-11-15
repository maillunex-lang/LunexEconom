"""EX-03 on isolated disposable PostgreSQL database lunex_ci only.
Every test rolls back or uses its own schema, never runs against production.
"""
import concurrent.futures
import os
import unittest
import uuid
from unittest import mock

CI=os.environ.get("LUNEX_DB_ENGINE")=="postgres" and os.environ.get("LUNEX_PG_DB")=="lunex_ci"
if CI:
    import city
    import economy
    import land
    import postgres_db

NOW=1_800_000_000

def rid(): return str(uuid.uuid4())

@unittest.skipUnless(CI,"requires isolated lunex_ci PostgreSQL")
class LandPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema="ex_land_"+uuid.uuid4().hex[:12]
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
            with cls.original_connect() as db:
                db.execute(f"DROP SCHEMA {cls.schema} CASCADE")
            raise

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()
        with cls.original_connect() as db:
            db.execute(f"DROP SCHEMA {cls.schema} CASCADE")

    def cmd(self,fn,owner,payload,now=NOW):
        with postgres_db.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(20261114)")
            return fn(db,"%s",owner,payload,now)

    def test_two_buyers_single_purchase_and_idempotency(self):
        with postgres_db.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(20261114)")
            for owner in ("alice", "bob"):
                economy.ensure_wallet(db,"%s",owner,NOW)
                economy.post(db,"%s","test_grant","PG isolated funds",
                             [(economy.player_account(owner),12_000_000),
                              (economy.TREASURY,-12_000_000)],NOW)
        request_ids={owner:rid() for owner in ("alice","bob")}
        def buy(owner):
            return self.cmd(land.buy,owner,{"px":1,"py":0,"request_id":request_ids[owner]})
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            responses=list(pool.map(buy,("alice","bob")))
        self.assertEqual(sorted(s for s,_ in responses),[201,409],responses)
        winning_name=next(name for name,resp in zip(("alice","bob"),responses) if resp[0]==201)
        replay=self.cmd(land.buy,winning_name,
                        {"px":1,"py":0,"request_id":request_ids[winning_name]})
        self.assertEqual(replay[0],200)
        with postgres_db.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM ledger_tx WHERE kind='land_buy'").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT SUM(balance) FROM wallets").fetchone()[0],0)

    @mock.patch.dict(os.environ,{"LAND_ENABLED":"1"})
    def test_schema_transactions_and_monthly_lease(self):
        with postgres_db.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(20261114)")
            economy.ensure_wallet(db,"%s","alice",NOW)
            economy.post(db,"%s","test_grant","PG isolated funds",
                         [(economy.player_account("alice"),10_000_000),
                          (economy.TREASURY,-10_000_000)],NOW)
        lease=self.cmd(land.lease,"alice",{"px":2,"py":1,"months":3,"request_id":rid()})
        self.assertEqual(lease[0],201,lease)
        with postgres_db.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(20261114)")
            land.monthly(db,"%s",0,NOW)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM ledger_tx WHERE kind='land_rent'").fetchone()[0],1)
            land.monthly(db,"%s",1,NOW+86400)
        with postgres_db.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM ledger_tx WHERE kind='land_rent'").fetchone()[0],2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM (SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0) b").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT SUM(balance) FROM wallets").fetchone()[0],0)
