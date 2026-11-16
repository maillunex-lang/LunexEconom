"""CAT1 construction materials: isolated PostgreSQL 16 and catalog invariants."""
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from server import db
from server.catalog import Catalog
from server.enterprises import core, api
from server.game_server import create_app, build_registry
from server.ledger.api import account, transfer, reconcile
from tools.validate_chains_proposal import load_proposal, validate

DSN = os.getenv('LUNEX_TEST_DATABASE_URL')
ROOT = Path(__file__).resolve().parents[2]


class CatalogChainsTests(unittest.TestCase):
    def test_complete_closed_catalog_and_sinks(self):
        data=load_proposal(ROOT / 'server/data')
        self.assertEqual(validate(data), [])
        self.assertEqual(tuple(len(data[k]) for k in ('products','buildings','recipes')),
                         (41,42,41))
        self.assertEqual(len(data['sinks']['product_exceptions']),0)
        self.assertEqual(len(Catalog().version),64)
        self.assertEqual(data['sinks']['logistics']['default'],0)
        self.assertEqual(data['sinks']['utility']['default'],0)

    def test_footprint_and_integer_rules(self):
        self.assertEqual(core.construction_norms(0,2,2),{'cement':80,'stone':120})
        self.assertEqual(core.construction_norms(1,2,2),{'steel':32,'wood':40})
        self.assertEqual(core.construction_norms(2,2,2),{'fabric':16,'boards':48})
        self.assertEqual(core.construction_norms(3,2,2),{})
        self.assertEqual(core.construction_norms(0,1,1),{'cement':20,'stone':30})
        proposal={b['id']:b for b in json.loads((ROOT / 'tools/sim/data/chains_proposed/buildings.json').read_text())}
        current={b['id']:b for b in Catalog().data['buildings']}
        for ident,b in current.items():
            if ident not in proposal:continue
            for k in ('upkeep_month','jobs','size'):
                self.assertEqual(b[k],proposal[ident][k],(ident,k))
            if ident in ('field','mill','bakery','grocery_store'):
                self.assertEqual(b['build_cost'],proposal[ident]['build_cost'])
            elif ident not in ('apiary','oil_well','refinery','dairy','slaughter','quarry',
                                'sawmill','cement_plant','steel_mill','textile',
                                'electronics_plant','warehouse','supermarket',
                                'clothing_store','office','housing'):
                self.assertEqual(b['build_cost'],proposal[ident]['build_cost']*260//1000)
        self.assertEqual(build_registry().flags['build_materials_required'],0)


@unittest.skipUnless(DSN,'Requires isolated PostgreSQL 16')
class ConstructionMaterialsPostgresTests(unittest.TestCase):
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
        username='cat1'+uuid4().hex[:12]
        uid=self.conn.execute("""INSERT INTO accounts(username,email,password_hash,role)
            VALUES(%s,%s,'test','player') RETURNING id""",
            (username,username+'@example.test')).fetchone()[0]
        wallet=account(self.conn,'player:'+username,'player',uid)
        if amount:
            transfer(self.conn,'cat1:fund:'+username,self.treasury,wallet,amount)
        return {'id':uid,'username':username,'wallet':wallet}

    def fixture(self,actor,days=8):
        px=5_000_000+int(uuid4().hex[:6],16)
        self.conn.execute("""INSERT INTO world_parcels(px,py,city_id,owner_kind,owner_ref)
            VALUES(%s,%s,NULL,'player',%s)""",(px,px,str(actor['id'])))
        order='cat1:'+uuid4().hex
        eid=self.conn.execute("""INSERT INTO enterprises
            (owner_id,building_id,px,py,x,y,width,height,name,build_cost,
             build_days,upkeep_month,jobs,storage_capacity,started_day,stage,
             recipe_id,build_request_id,build_transfer_id)
             VALUES(%s,'field',%s,%s,%s,%s,2,2,'CAT1 field',39000,%s,
               0,0,4000,0,0,'field_grain',%s,NULL)
             RETURNING id""",
             (actor['id'],px,px,px*6,px*6,days,order)).fetchone()[0]
        return eid,order

    def balance(self,actor):
        return self.conn.execute('SELECT balance FROM ledger_accounts WHERE id=%s',
                                 (actor['wallet'],)).fetchone()[0]

    def wait(self,eid):
        return self.conn.execute("""SELECT stage,amount,waiting_days,reason,missing
            FROM enterprise_build_waits WHERE enterprise_id=%s""",(eid,)).fetchone()

    def stage(self,eid):
        return self.conn.execute('SELECT stage,stage_progress_days FROM enterprises WHERE id=%s',
                                 (eid,)).fetchone()

    def test_foundation_wait_requires_80_cement_120_stone_and_exactly_once(self):
        actor=self.owner(39000)
        eid,order=self.fixture(actor)
        core.advance_day(self.conn,1,materials_required=True)
        self.assertEqual(self.stage(eid),(0,0))
        self.assertEqual(self.wait(eid)[3],'materials')
        self.assertEqual(self.wait(eid)[4]['materials'],{'cement':80,'stone':120})
        self.assertEqual(self.balance(actor),39000)
        core.adjust(self.conn,eid,'cement',79)
        core.adjust(self.conn,eid,'stone',120)
        core.advance_day(self.conn,2,materials_required=True)
        self.assertEqual(self.wait(eid)[4]['materials'],{'cement':1})
        self.assertEqual(self.wait(eid)[2],2)
        self.assertEqual(self.balance(actor),39000)
        core.adjust(self.conn,eid,'cement',1)
        core.advance_day(self.conn,3,materials_required=True)
        self.assertEqual(self.stage(eid),(0,1))
        self.assertEqual(self.balance(actor),27300)
        self.assertEqual(core.stock(self.conn,eid)['cement']['quantity'],0)
        self.assertEqual(core.stock(self.conn,eid)['stone']['quantity'],0)
        self.assertIsNone(self.wait(eid))
        self.assertTrue(core._pay_build_stage(self.conn,eid,actor['id'],0,11700,3,True))
        core.advance_day(self.conn,3,materials_required=True)
        self.assertEqual(self.balance(actor),27300)
        self.assertEqual(self.stage(eid),(0,1))
        self.assertEqual(self.conn.execute(
            'SELECT count(*) FROM ledger_transfers WHERE request_id=%s',
            ('enterprise:build:'+order,)).fetchone()[0],1)
        self.assertEqual(self.conn.execute(
            'SELECT count(*) FROM enterprise_stage_payments WHERE enterprise_id=%s AND stage=0',
            (eid,)).fetchone()[0],1)
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_money_and_materials_both_gate_atomic_installment(self):
        actor=self.owner(0)
        eid,order=self.fixture(actor)
        core.adjust(self.conn,eid,'cement',80)
        core.adjust(self.conn,eid,'stone',120)
        core.advance_day(self.conn,1,materials_required=True)
        self.assertEqual(self.stage(eid),(0,0))
        self.assertEqual(self.wait(eid)[3],'money')
        self.assertEqual(self.wait(eid)[4]['money'],11700)
        self.assertEqual(core.stock(self.conn,eid)['cement']['quantity'],80)
        transfer(self.conn,'cat1:refill:'+order,self.treasury,actor['wallet'],39000)
        core.advance_day(self.conn,2,materials_required=True)
        self.assertEqual(self.balance(actor),27300)
        self.assertEqual(core.stock(self.conn,eid)['stone']['quantity'],0)
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_frame_wait_and_replayed_stage(self):
        actor=self.owner(39000)
        eid,order=self.fixture(actor)
        core.adjust(self.conn,eid,'cement',80)
        core.adjust(self.conn,eid,'stone',120)
        core.advance_day(self.conn,1,materials_required=True)
        core.advance_day(self.conn,2,materials_required=True)
        self.assertEqual(self.stage(eid)[0],0)
        self.assertEqual(self.wait(eid)[0],1)
        self.assertEqual(self.wait(eid)[4]['materials'],{'steel':32,'wood':40})
        self.assertEqual(self.balance(actor),27300)
        core.adjust(self.conn,eid,'steel',32)
        core.adjust(self.conn,eid,'wood',40)
        core.advance_day(self.conn,3,materials_required=True)
        self.assertEqual(self.stage(eid)[0],1)
        self.assertEqual(self.balance(actor),11700)
        self.assertEqual(core.stock(self.conn,eid)['steel']['quantity'],0)
        self.assertTrue(core._pay_build_stage(self.conn,eid,actor['id'],1,15600,3,True))
        self.assertEqual(self.balance(actor),11700)
        self.assertEqual(self.conn.execute(
            'SELECT count(*) FROM ledger_transfers WHERE request_id=%s',
            (f'enterprise:build:{eid}:1',)).fetchone()[0],1)
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_api_only_exposes_materials_when_enabled(self):
        actor=self.owner(0)
        eid,order=self.fixture(actor)
        context={'conn':self.conn,'path_params':{'id':str(eid)},
                 'settings':{'build_materials_required':1}}
        with patch('server.enterprises.api.authenticate',return_value=actor):
            status,one=api.one({},context)
            _,listing=api.list_own({},context)
            self.assertEqual(status,200)
            self.assertEqual(one['materials_required']['stage'],'foundation')
            self.assertEqual(one['materials_required']['items'][0],
                             {'product_id':'cement','needed':80,'have':0})
            self.assertEqual(one['materials_required']['short'][1],
                             {'product_id':'stone','missing':120})
            self.assertIn('materials_required',listing['items'][0])
            context['settings']['build_materials_required']=0
            self.assertNotIn('materials_required',api.one({},context)[1])
            self.assertNotIn('materials_required',api.list_own({},context)[1]['items'][0])

    def test_flag_zero_fundament_ignores_stock(self):
        actor=self.owner(39000)
        eid,order=self.fixture(actor)
        self.assertTrue(core._pay_build_stage(self.conn,eid,actor['id'],0,11700,0))
        core.advance_day(self.conn,1,materials_required=False)
        self.assertEqual(self.balance(actor),27300)
        self.assertEqual(self.stage(eid),(0,1))
        self.assertIsNone(self.wait(eid))
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_deferred_foundation_is_paid_after_flag_is_disabled(self):
        actor=self.owner(39000)
        eid,order=self.fixture(actor)
        core.advance_day(self.conn,1,materials_required=True)
        self.assertEqual(self.wait(eid)[3],'materials')
        core.advance_day(self.conn,2,materials_required=False)
        self.assertEqual(self.balance(actor),27300)
        self.assertEqual(self.stage(eid),(0,1))
        self.assertIsNone(self.wait(eid))
        self.assertEqual(self.conn.execute(
            'SELECT count(*) FROM ledger_transfers WHERE request_id=%s',
            ('enterprise:build:'+order,)).fetchone()[0],1)
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_existing_paid_foundation_does_not_consume_on_flag_enable(self):
        actor=self.owner(39000)
        eid,order=self.fixture(actor)
        core._pay_build_stage(self.conn,eid,actor['id'],0,11700,0)
        core.advance_day(self.conn,1,materials_required=True)
        core.advance_day(self.conn,2,materials_required=True)
        self.assertEqual(self.balance(actor),27300)
        self.assertEqual(self.wait(eid)[0],1)
        self.assertEqual(self.wait(eid)[3],'materials')
        self.assertEqual(self.conn.execute(
            'SELECT count(*) FROM enterprise_stage_payments WHERE enterprise_id=%s AND stage=0',
            (eid,)).fetchone()[0],1)
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_placement_flag_one_waits_without_charging_and_request_is_idempotent(self):
        actor=self.owner(0)
        px=6_000_000+int(uuid4().hex[:6],16)
        x=px*6
        self.conn.execute("""INSERT INTO world_parcels(px,py,city_id,owner_kind,owner_ref)
            VALUES(%s,%s,NULL,'player',%s)""",(px,px,str(actor['id'])))
        req='cat1-order:'+uuid4().hex
        cells={(x+a,x+b) for a in range(2) for b in range(2)}
        with patch('server.enterprises.core.placement',
                   return_value=(None,cells,None,[])), patch(
                   'server.enterprises.core.world._touch',return_value=1):
            status,result=core.place(self.conn,actor,req,'field',px,px,x,x,True)
            self.assertEqual(status,201,result)
            self.assertIsNone(result['transfer_id'])
            self.assertEqual(result['initial_payment'],11700)
            eid=result['id']
            self.assertIsNone(self.conn.execute(
                'SELECT build_transfer_id FROM enterprises WHERE id=%s',(eid,)).fetchone()[0])
            self.assertEqual(self.wait(eid)[3],'money')
            self.assertEqual(self.wait(eid)[4]['materials'],{'cement':80,'stone':120})
            self.assertEqual(self.balance(actor),0)
            status,again=core.place(self.conn,actor,req,'field',px,px,x,x,True)
            self.assertEqual(status,200,again)
            self.assertTrue(again['idempotent'])
            self.assertEqual(self.conn.execute(
                'SELECT count(*) FROM enterprises WHERE build_request_id=%s',
                (req,)).fetchone()[0],1)
            self.assertEqual(self.conn.execute(
                'SELECT count(*) FROM ledger_transfers WHERE request_id=%s',
                ('enterprise:build:'+req,)).fetchone()[0],0)
            self.assertTrue(reconcile(self.conn)['ok'])
