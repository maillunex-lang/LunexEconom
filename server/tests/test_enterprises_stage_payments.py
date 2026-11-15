"""V2-04d staged construction: integer formulas and isolated PostgreSQL checks."""
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from server import db
from server.game_server import create_app
from server.enterprises import core, api
from server.ledger.api import account, transfer, reconcile
from server.world import core as world

DSN = os.getenv('LUNEX_TEST_DATABASE_URL')


class StagePaymentMathTests(unittest.TestCase):
    def test_catalog_exact_cost_and_remainder(self):
        expected = {
            'field': (150000, (45000,60000,30000,15000)),
            'mill': (250000, (75000,100000,50000,25000)),
            'bakery': (300000, (90000,120000,60000,30000)),
            'grocery_store': (200000, (60000,80000,40000,20000)),
        }
        for building, (total, stages) in expected.items():
            with self.subTest(building=building):
                self.assertEqual(core.catalog().index['buildings'][building]['build_cost'],total)
                self.assertEqual(core.stage_costs(total),stages)
                self.assertEqual(sum(stages),total)
        for total in (1,2,3,7,999,1001,2**53-1):
            with self.subTest(total=total):
                self.assertEqual(sum(core.stage_costs(total)),total)
                self.assertTrue(all(isinstance(x,int) and x>=0 for x in core.stage_costs(total)))

    def test_time_boundaries_match_simulator(self):
        from tools.sim.formulas import split_by_bp, TIME_SHARE_BP
        for days in (1,2,3,4,8,12,18,37):
            self.assertEqual(core.stage_day_lengths(days),
                             tuple(split_by_bp(days,TIME_SHARE_BP)))


@unittest.skipUnless(DSN,'Requires isolated PostgreSQL 16')
class StagePaymentPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=create_app(DSN)

    @classmethod
    def tearDownClass(cls):
        cls.app.close()

    def setUp(self):
        self.conn=db.connect(DSN)
        self.treasury=account(self.conn,'system:treasury')

    def tearDown(self):
        self.conn.rollback()
        self.conn.close()

    def owner(self,amount):
        name='stage'+uuid4().hex[:12]
        owner=self.conn.execute("""INSERT INTO accounts(username,email,password_hash,role)
          VALUES(%s,%s,'test-hash','player') RETURNING id""",
          (name,name+'@example.test')).fetchone()[0]
        wallet=account(self.conn,'player:'+name,'player',owner)
        if amount:
            transfer(self.conn,'stage:fund:'+name,self.treasury,wallet,amount)
        return {'id':owner,'username':name,'wallet':wallet}

    def balance(self,actor):
        return self.conn.execute('SELECT balance FROM ledger_accounts WHERE id=%s',
                                 (actor['wallet'],)).fetchone()[0]

    def fixture(self,owner,building='field',stage=0,days=None):
        """A valid synthetic parcel for daily ticks, independent of terrain generation."""
        info=core.catalog().index['buildings'][building]
        px=10000000+owner['id']*20+int(uuid4().hex[:5],16)
        py=px
        self.conn.execute("""INSERT INTO world_parcels(px,py,city_id,owner_kind,owner_ref)
            VALUES(%s,%s,NULL,'player',%s)""",(px,py,str(owner['id'])))
        receipt=transfer(self.conn,'stage:legacy-receipt:'+uuid4().hex,
                         self.treasury,owner['wallet'],1)
        eid=self.conn.execute("""INSERT INTO enterprises
          (owner_id,building_id,px,py,x,y,width,height,name,build_cost,
           build_days,upkeep_month,jobs,storage_capacity,started_day,stage,
           recipe_id,build_request_id,build_transfer_id)
          VALUES(%s,%s,%s,%s,%s,%s,1,1,'test',%s,%s,0,0,4000,0,%s,NULL,%s,%s)
          RETURNING id""",
          (owner['id'],building,px,py,px*6,py*6,info['build_cost'],
           days or info['build_days'],stage,uuid4().hex,receipt)).fetchone()[0]
        return eid

    def pay_first(self,owner,eid):
        info=self.conn.execute('SELECT build_cost FROM enterprises WHERE id=%s',(eid,)).fetchone()
        amount=core.stage_costs(info[0])[0]
        self.assertTrue(core._pay_build_stage(self.conn,eid,owner['id'],0,amount,0))
        return amount

    def stage(self,eid):
        return self.conn.execute('SELECT stage FROM enterprises WHERE id=%s',(eid,)).fetchone()[0]

    def test_first_payment_rejected_without_funds_then_paid(self):
        owner=self.owner(0)
        eid=self.fixture(owner,days=8)
        first=core.stage_costs(150000)[0]
        self.assertFalse(core._pay_build_stage(self.conn,eid,owner['id'],0,first,0))
        self.assertEqual(self.stage(eid),0)
        self.assertEqual(self.conn.execute(
            'SELECT count(*) FROM enterprise_stage_payments WHERE enterprise_id=%s',
            (eid,)).fetchone()[0],0)
        transfer(self.conn,'stage:deposit:'+uuid4().hex,
                 self.treasury,owner['wallet'],first)
        self.assertTrue(core._pay_build_stage(self.conn,eid,owner['id'],0,first,0))
        self.assertTrue(core._pay_build_stage(self.conn,eid,owner['id'],0,first,0))
        self.assertEqual(self.balance(owner),1)
        self.assertEqual(self.conn.execute(
            'SELECT count(*) FROM enterprise_stage_payments WHERE enterprise_id=%s',
            (eid,)).fetchone()[0],1)
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_short_build_paid_in_four_exact_stages(self):
        owner=self.owner(150000)
        eid=self.fixture(owner,days=1)
        initial=self.pay_first(owner,eid)
        self.assertEqual(initial,45000)
        core.advance_day(self.conn,1)
        self.assertEqual(self.stage(eid),4)
        self.assertEqual(sum(r[0] for r in self.conn.execute(
            'SELECT amount FROM enterprise_stage_payments WHERE enterprise_id=%s',(eid,))),150000)
        self.assertEqual(self.balance(owner),1)
        counts=self.conn.execute('SELECT count(*) FROM ledger_transfers '
                                 'WHERE request_id LIKE %s',
                                 (f'enterprise:build:{eid}:%',)).fetchone()[0]
        self.assertEqual(counts,4)
        core.advance_day(self.conn,1)
        self.assertEqual(self.balance(owner),1)
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_underfunded_wait_and_delayed_resume(self):
        owner=self.owner(45000)
        eid=self.fixture(owner,days=8)
        self.pay_first(owner,eid)
        core.advance_day(self.conn,1)
        core.advance_day(self.conn,2)
        self.assertEqual(self.stage(eid),0)
        self.assertEqual(self.conn.execute('SELECT stage,amount,waiting_days FROM '
            'enterprise_build_waits WHERE enterprise_id=%s',(eid,)).fetchone(),(1,60000,1))
        core.advance_day(self.conn,2)
        self.assertEqual(self.conn.execute('SELECT waiting_days FROM '
            'enterprise_build_waits WHERE enterprise_id=%s',(eid,)).fetchone()[0],1)
        core.advance_day(self.conn,3)
        self.assertEqual(self.conn.execute('SELECT waiting_days FROM '
            'enterprise_build_waits WHERE enterprise_id=%s',(eid,)).fetchone()[0],2)
        self.assertEqual(self.balance(owner),1)
        transfer(self.conn,'stage:refill:'+uuid4().hex,self.treasury,owner['wallet'],105000)
        core.advance_day(self.conn,4)
        self.assertEqual(self.stage(eid),1)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM enterprise_build_waits '
            'WHERE enterprise_id=%s',(eid,)).fetchone()[0],0)
        # The remaining stages must take fresh days, not catch up immediately.
        self.assertEqual(self.stage(eid),1)
        for day in range(5,22):
            core.advance_day(self.conn,day)
        self.assertEqual(self.stage(eid),4)
        self.assertEqual(self.balance(owner),1)
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_unfinished_sale_returns_only_paid_half(self):
        owner=self.owner(45000)
        eid=self.fixture(owner,days=8)
        self.pay_first(owner,eid)
        with patch('server.enterprises.api.authenticate',return_value=owner), \
             patch('server.enterprises.api.world.clear_occupied'):
            status,result=api.sell({'request_id':uuid4().hex},
                 {'conn':self.conn,'path_params':{'id':str(eid)}})
        self.assertEqual(status,200,result)
        self.assertEqual(result['price'],22500)
        self.assertEqual(self.balance(owner),22501)

    def test_legacy_paid_enterprise_stays_operational(self):
        owner=self.owner(10000)
        eid=self.fixture(owner,stage=4)
        # Existing rows migrated as legacy_prepaid; independent fixtures can
        # manually seed the same compatible paid-state without fake journals.
        self.conn.execute("""INSERT INTO enterprise_stage_payments
          (enterprise_id,stage,amount,legacy_prepaid)
          SELECT %s,s.stage,CASE WHEN s.stage=0 THEN 45000
             WHEN s.stage=1 THEN 60000 WHEN s.stage=2 THEN 30000
             ELSE 15000 END,true FROM generate_series(0,3) AS s(stage)""",(eid,))
        details=core.payment_status(self.conn,eid,4,150000)
        self.assertEqual(details['paid_amount'],150000)
        self.assertIsNone(details['next_payment'])
        core.advance_day(self.conn,1)
        self.assertEqual(self.stage(eid),4)
        self.assertTrue(reconcile(self.conn)['ok'])


if __name__=='__main__':
    unittest.main()
