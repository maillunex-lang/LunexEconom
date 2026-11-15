"""Real PostgreSQL 16 commissioning tests, isolated disposable lunex_ci only."""
import os
import unittest
import uuid
from unittest.mock import patch

import citygen
import regions
import economy
import postgres_db
import postgres_world

T0 = 1_800_000_000
MONTH = 86400
STEP = 8400


@unittest.skipUnless(os.environ.get('LUNEX_DB_ENGINE') == 'postgres'
                     and os.environ.get('LUNEX_PG_DB') == 'lunex_ci',
                     'requires isolated lunex_ci PostgreSQL database')
class PostgreSQLCommissioningTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            'LUNEX_CONSTRUCTION_STEP_SECONDS': str(STEP),
            'LUNEX_MONTH_SECONDS': str(MONTH),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        with postgres_db.connect() as db:
            citygen.ensure(db, '%s')
            regions.ensure(db, '%s')
            # Isolated economy fixture uses pre-generated, unzoned world rules.
            db.execute('DELETE FROM geo_seed')
            db.execute('TRUNCATE TABLE ledger_entries,ledger_tx,wallets,inventory,'
                       'company_reports,monthly_reports,company_state,market_prices,'
                       'building_ops,cells,roads,buildings,events,chunks,commands,'
                       'world_state,world_clock RESTART IDENTITY CASCADE')

    def test_commissioning_and_monthly_production(self):
        owner='pg_edition_'+uuid.uuid4().hex[:12]
        with patch.object(postgres_world.time, 'time', return_value=T0):
            status, data=postgres_world.build(owner,{'kind':'farm','x':8,'y':10,'request_id':str(uuid.uuid4())})
            self.assertEqual(status,201,data)
            oid=data['object_id']
            pending=postgres_world.wallet(owner)[1]
            self.assertEqual(pending['labor']['jobs'],0)
            self.assertEqual(pending['forecast']['buildings'],0)
            with postgres_db.connect() as db:
                month, permille=db.execute('SELECT start_month,start_permille FROM building_ops WHERE object_id=%s',(oid,)).fetchone()
                self.assertEqual(month,0)
                self.assertEqual(permille, STEP * 2 * 1000 // MONTH)
        with patch.object(postgres_world.time,'time',return_value=T0+2*STEP):
            active=postgres_world.wallet(owner)[1]
            self.assertEqual(active['forecast']['buildings'],1)
        with patch.object(postgres_world.time,'time',return_value=T0+MONTH+5):
            postgres_world.wallet(owner)
            with postgres_db.connect() as db:
                supply=db.execute("SELECT supply FROM market_prices WHERE product='honey' AND month_index=0").fetchone()[0]
                self.assertEqual(supply,economy.PRODUCTION['farm']['output']*(1000-permille)//1000)
                self.assertEqual(db.execute('SELECT stage FROM construction_stages WHERE object_id=%s',(oid,)).fetchone()[0],'complete')
                self.assertFalse(db.execute('SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0').fetchall())
            result=postgres_world.events(0)[1]['events']
            self.assertEqual([e['construction_stage'] for e in result if e['kind']=='building_created' and e['object_id']==oid],
                             ['foundation','complete'])

    def test_late_build_does_not_produce_previous_month(self):
        owner='pg_late_'+uuid.uuid4().hex[:12]
        with patch.object(postgres_world.time,'time',return_value=T0):
            postgres_world.clock_state()
        with patch.object(postgres_world.time,'time',return_value=T0+MONTH-6000):
            status,res=postgres_world.build(owner,{'kind':'farm','x':8,'y':10,'request_id':str(uuid.uuid4())})
            self.assertEqual(status,201,res)
        with patch.object(postgres_world.time,'time',return_value=T0+MONTH+5):
            postgres_world.wallet(owner)
            with postgres_db.connect() as db:
                self.assertEqual(db.execute("SELECT supply FROM market_prices WHERE product='honey' AND month_index=0").fetchone(),(0,))
        with patch.object(postgres_world.time,'time',return_value=T0+2*MONTH+5):
            postgres_world.wallet(owner)
            with postgres_db.connect() as db:
                self.assertGreater(db.execute("SELECT supply FROM market_prices WHERE product='honey' AND month_index=1").fetchone()[0],0)