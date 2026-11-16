"""Sales V2 isolated PostgreSQL 16 integration, rollback per fixture."""
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from server import db
from server.game_server import create_app, build_registry
from server.sales import api,core
from server.enterprises import core as enterprises
from server.ledger.api import reconcile
from server.tests.test_supply_postgres import SupplyPostgresTests

DSN=os.getenv('LUNEX_TEST_DATABASE_URL')


@unittest.skipUnless(DSN,'isolated PostgreSQL 16 only')
class SalesPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=create_app(DSN)

    @classmethod
    def tearDownClass(cls):
        cls.app.close()

    setUp = SupplyPostgresTests.setUp
    tearDown = SupplyPostgresTests.tearDown
    owner = SupplyPostgresTests.owner
    enterprise = SupplyPostgresTests.enterprise
    qty = SupplyPostgresTests.qty

    def _flags(self):
        return {**self.app.registry.flags,'supply_sales_modes_enabled':True}

    @property
    def flags(self):
        return self._flags()

    def ctx(self,owner,eid,product='grain'):
        return {'conn':self.conn,'settings':self.flags,
                'path_params':{'id':str(eid),'product':product}}

    def policy(self,owner,eid,mode='public',reserve=0,price=25,product='grain',**extra):
        ctx=self.ctx(owner,eid,product)
        data={'mode':mode,'reserve_bp':reserve,'price':price,
              'expected_version':0,'request_id':'pol:'+uuid4().hex,**extra}
        with patch('server.sales.api.authenticate',return_value=owner):
            return api.policy_put(data,ctx)

    def test_flag_off_and_routes(self):
        registry=build_registry()
        self.assertIs(registry.flags['supply_sales_modes_enabled'],False)
        self.assertIn(('GET','/supply/offers'),registry.routes)
        self.assertIn(('PUT','/enterprises/{id}/sales-policy/{product}'),registry.routes)
        self.assertEqual([n for _,n,_ in sorted(registry.tick_handlers['daily'])][:2],
                         ['supply_links','supply_market'])
        self.assertEqual(api.offers({}, {'conn':self.conn,'settings':{},'query':{}})[0],401)

    def test_policy_owner_permissions(self):
        mine=self.owner();outsider=self.owner()
        eid=self.enterprise(mine,'field',recipe='field_grain')
        ctx=self.ctx(outsider,eid)
        with patch('server.sales.api.authenticate',return_value=outsider):
            self.assertEqual(api.policy_get({},ctx)[0],404)
            self.assertEqual(api.policy_put({},ctx)[0],404)
        with patch('server.sales.api.authenticate',return_value=None):
            self.assertEqual(api.policy_get({},ctx)[0],401)

    def test_four_modes_and_pending_policy(self):
        for mode in ('private','public','mixed','invited'):
            with self.subTest(mode=mode):
                mine=self.owner();eid=self.enterprise(mine,'field',recipe='field_grain')
                status,data=self.policy(mine,eid,mode,reserve=3000 if mode=='mixed' else 0)
                self.assertEqual(status,200,data)
                self.assertEqual(data['effective_day'],enterprises.today(self.conn)+1)
                self.assertIsNone(core.current_policy(self.conn,eid,'grain',data['effective_day']-1))
                self.assertEqual(core.current_policy(self.conn,eid,'grain',data['effective_day'])['mode'],mode)

    def test_price_bounds_and_version(self):
        mine=self.owner();eid=self.enterprise(mine,'field',recipe='field_grain')
        for value in (12,75):
            status,data=self.policy(mine,eid,price=value,dry_run=True)
            self.assertEqual(status,200,data)
        for value in (11,76,12.5,True,-1):
            self.assertEqual(self.policy(mine,eid,price=value)[0],400)
        self.assertEqual(self.policy(mine,eid,price=25)[0],200)
        self.assertEqual(self.policy(mine,eid,price=26)[0],409)

    def test_policy_idempotency(self):
        mine=self.owner();eid=self.enterprise(mine,'field',recipe='field_grain')
        ctx=self.ctx(mine,eid)
        data={'mode':'public','reserve_bp':0,'price':25,
              'expected_version':0,'request_id':'policy:'+uuid4().hex}
        with patch('server.sales.api.authenticate',return_value=mine):
            self.assertEqual(api.policy_put(data,ctx)[0],200)
            status,result=api.policy_put(data,ctx)
        self.assertEqual(status,200)
        self.assertTrue(result['idempotent'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM sales_policy_changes WHERE enterprise_id=%s',(eid,)).fetchone()[0],1)

    def test_policy_dry_run_no_mutation(self):
        mine=self.owner();eid=self.enterprise(mine,'field',recipe='field_grain')
        status,data=self.policy(mine,eid,dry_run=True)
        self.assertEqual(status,200)
        self.assertIsNone(core.pending_policy(self.conn,eid,'grain'))

    def test_unknown_output_rejected(self):
        mine=self.owner();eid=self.enterprise(mine,'field',recipe='field_grain')
        self.assertEqual(self.policy(mine,eid,product='flour')[0],404)

    def test_contract_reserves_actual_stock(self):
        seller=self.owner();buyer=self.owner()
        field=self.enterprise(seller,'field',recipe='field_grain',stock=[('grain',100,80)])
        mill=self.enterprise(buyer,'mill',recipe='mill_flour')
        self.policy(seller,field)
        data={'seller_enterprise_id':field,'buyer_enterprise_id':mill,
              'product_id':'grain','volume':70,'start_day':enterprises.today(self.conn),'end_day':enterprises.today(self.conn)+5,
              'price':25,'request_id':'contract:'+uuid4().hex}
        with patch('server.sales.api.authenticate',return_value=seller):
            status,response=api.contract(data,{'conn':self.conn,'settings':self.flags})
            self.assertEqual(status,201,response)
            self.assertEqual(api.contract(data,{'conn':self.conn,'settings':self.flags})[0],200)
        self.assertEqual(core.reserve_for_contracts(self.conn,field,'grain',enterprises.today(self.conn)),70)
        self.assertEqual(core.offer_quantities(100,'public',0,70),(0,70,30))

    def test_contract_cannot_oversubscribe(self):
        seller=self.owner();buyer=self.owner()
        field=self.enterprise(seller,'field',recipe='field_grain',stock=[('grain',20,80)])
        mill=self.enterprise(buyer,'mill',recipe='mill_flour')
        data={'seller_enterprise_id':field,'buyer_enterprise_id':mill,
              'product_id':'grain','volume':21,'start_day':enterprises.today(self.conn),'end_day':enterprises.today(self.conn)+5,
              'price':25,'request_id':'contract:'+uuid4().hex}
        with patch('server.sales.api.authenticate',return_value=seller):
            self.assertEqual(api.contract(data,{'conn':self.conn,'settings':self.flags})[0],409)

    def test_sales_purchase_ledger_stock_and_idempotency(self):
        seller=self.owner();buyer=self.owner()
        field=self.enterprise(seller,'field',recipe='field_grain',stock=[('grain',100,80)])
        mill=self.enterprise(buyer,'mill',recipe='mill_flour')
        self.policy(seller,field)
        ctx={'conn':self.conn,'settings':self.flags}
        request={'buyer_enterprise_id':mill,'seller_enterprise_id':field,
                 'product_id':'grain','quantity':20,'request_id':'purchase:'+uuid4().hex}
        with patch('server.sales.api.authenticate',return_value=buyer):
            self.assertEqual(api.purchase(request,ctx)[0],403) # effective next day
        # advance completed ticks to enable policy in a test rollback transaction.
        self.conn.execute('''INSERT INTO game_ticks(day_index,completed) VALUES(%s,true)
            ON CONFLICT(day_index) DO UPDATE SET completed=true''', (enterprises.today(self.conn),))
        with patch('server.sales.api.authenticate',return_value=buyer):
            status,data=api.purchase(request,ctx)
            self.assertEqual(status,201,data)
            self.assertEqual(api.purchase(request,ctx)[0],200)
        self.assertEqual(self.qty(field,'grain'),80)
        self.assertEqual(self.qty(mill,'grain'),20)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM sales_purchase_receipts WHERE request_id=%s',(request['request_id'],)).fetchone()[0],1)
        self.assertEqual(self.conn.execute('''SELECT coalesce(sum(amount),0) FROM ledger_entries''').fetchone()[0],0)

    def test_quota_and_manual_no_fake_supply(self):
        seller=self.owner();buyer=self.owner()
        field=self.enterprise(seller,'field',recipe='field_grain',stock=[('grain',10,80)])
        mill=self.enterprise(buyer,'mill',recipe='mill_flour')
        self.policy(seller,field)
        self.conn.execute('''INSERT INTO game_ticks(day_index,completed) VALUES(%s,true)
            ON CONFLICT(day_index) DO UPDATE SET completed=true''',(enterprises.today(self.conn),))
        ctx={'conn':self.conn,'settings':self.flags}
        with patch('server.sales.api.authenticate',return_value=buyer):
            for quantity in (5,11,100):
                status,data=api.purchase({'buyer_enterprise_id':mill,
                    'seller_enterprise_id':field,'product_id':'grain',
                    'quantity':quantity,'request_id':str(uuid4())},ctx)
                self.assertEqual(status,409,data)
        self.assertEqual(self.qty(field,'grain'),10)

    def test_empty_day_receipt_idempotent(self):
        core.clear_day(self.conn,90000,self.flags)
        core.clear_day(self.conn,90000,self.flags)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM sales_day_receipts WHERE day_index=90000').fetchone()[0],1)

    def test_get_offers_does_not_expose_private_stock(self):
        seller=self.owner();buyer=self.owner()
        field=self.enterprise(seller,'field',recipe='field_grain',stock=[('grain',100,80)])
        self.policy(seller,field,mode='private')
        self.conn.execute('''INSERT INTO game_ticks(day_index,completed) VALUES(%s,true)
            ON CONFLICT(day_index) DO UPDATE SET completed=true''',(enterprises.today(self.conn),))
        ctx={'conn':self.conn,'settings':self.flags,'query':{'city':['ufa'],'product':['grain']}}
        with patch('server.sales.api.authenticate',return_value=buyer):
            status,data=api.offers({},ctx)
            self.assertEqual(status,200)
            self.assertFalse(any(o['seller_enterprise_id']==field for o in data['offers']))

    def test_disabled_policy_endpoint(self):
        mine=self.owner();eid=self.enterprise(mine,'field',recipe='field_grain')
        ctx=self.ctx(mine,eid);ctx['settings']={'supply_sales_modes_enabled':False}
        with patch('server.sales.api.authenticate',return_value=mine):
            self.assertEqual(api.policy_get({},ctx)[0],404)

    def test_reliability_neutral(self):
        mine=self.owner();eid=self.enterprise(mine,'field',recipe='field_grain')
        self.assertEqual(core.reliability(self.conn,eid,'grain',0),700)

    def test_own_policy_dry_run_future(self):
        mine=self.owner();eid=self.enterprise(mine,'field',recipe='field_grain')
        status,data=self.policy(mine,eid,dry_run=True)
        self.assertEqual(status,200)
        self.assertEqual(data['effective_day'],enterprises.today(self.conn)+1)

    def test_policy_reserve_validation(self):
        mine=self.owner();eid=self.enterprise(mine,'field',recipe='field_grain')
        self.assertEqual(self.policy(mine,eid,mode='public',reserve=3000)[0],400)

    def test_policy_request_id_malformed(self):
        mine=self.owner();eid=self.enterprise(mine,'field',recipe='field_grain')
        self.assertEqual(self.policy(mine,eid,request_id='bad request')[0],400)

    def test_policies_dont_change_inventory(self):
        mine=self.owner();eid=self.enterprise(mine,'field',recipe='field_grain',stock=[('grain',50,80)])
        self.policy(mine,eid)
        self.assertEqual(self.qty(eid,'grain'),50)

    def test_empty_offers_without_auth(self):
        self.assertEqual(api.offers({}, {'conn':self.conn,'settings':self.flags,'query':{}})[0],401)

    def test_contract_other_owner_rejected(self):
        seller=self.owner();buyer=self.owner();outsider=self.owner()
        field=self.enterprise(seller,'field',recipe='field_grain',stock=[('grain',50,80)])
        mill=self.enterprise(buyer,'mill',recipe='mill_flour')
        data={'seller_enterprise_id':field,'buyer_enterprise_id':mill,
              'product_id':'grain','volume':10,'start_day':enterprises.today(self.conn),'end_day':enterprises.today(self.conn)+5,
              'price':25,'request_id':str(uuid4())}
        with patch('server.sales.api.authenticate',return_value=outsider):
            self.assertEqual(api.contract(data,{'conn':self.conn,'settings':self.flags})[0],404)

    def test_foreign_daily_hidden(self):
        mine=self.owner();outsider=self.owner();eid=self.enterprise(mine,'field',recipe='field_grain')
        with patch('server.sales.api.authenticate',return_value=outsider):
            self.assertEqual(api.daily({},self.ctx(outsider,eid))[0],404)

    def test_daily_no_private_exact_inventory(self):
        mine=self.owner();eid=self.enterprise(mine,'field',recipe='field_grain')
        with patch('server.sales.api.authenticate',return_value=mine):
            status,data=api.daily({},self.ctx(mine,eid))
        self.assertEqual(status,200)
        self.assertEqual(data['products'],[])

    def test_contract_request_id_conflict(self):
        seller=self.owner();buyer=self.owner()
        field=self.enterprise(seller,'field',recipe='field_grain',stock=[('grain',50,70)])
        mill=self.enterprise(buyer,'mill',recipe='mill_flour')
        day=enterprises.today(self.conn)
        payload={'seller_enterprise_id':field,'buyer_enterprise_id':mill,
                 'product_id':'grain','volume':20,'start_day':day,'end_day':day+5,
                 'price':25,'request_id':'ct:'+uuid4().hex}
        with patch('server.sales.api.authenticate',return_value=seller):
            self.assertEqual(api.contract(payload,{'conn':self.conn,'settings':self.flags})[0],201)
            self.assertEqual(api.contract({**payload,'volume':21},
                             {'conn':self.conn,'settings':self.flags})[0],409)

    def test_invalid_contract_term(self):
        seller=self.owner();buyer=self.owner()
        field=self.enterprise(seller,'field',recipe='field_grain',stock=[('grain',50,70)])
        mill=self.enterprise(buyer,'mill',recipe='mill_flour')
        day=enterprises.today(self.conn)
        payload={'seller_enterprise_id':field,'buyer_enterprise_id':mill,
                 'product_id':'grain','volume':10,'start_day':day+8,
                 'end_day':day+7,'price':25,'request_id':'ct:'+uuid4().hex}
        with patch('server.sales.api.authenticate',return_value=seller):
            self.assertEqual(api.contract(payload,{'conn':self.conn,'settings':self.flags})[0],400)

    def test_invited_only_visibility(self):
        seller=self.owner();buyer=self.owner()
        field=self.enterprise(seller,'field',recipe='field_grain',stock=[('grain',100,70)])
        self.policy(seller,field,mode='invited',invited_owner_ids=[buyer['id']])
        self.conn.execute('INSERT INTO game_ticks(day_index,completed) VALUES(%s,true) '
                          'ON CONFLICT(day_index) DO UPDATE SET completed=true',
                          (enterprises.today(self.conn),))
        self.assertTrue(core.seller_allowed(self.conn,field,buyer['id'],'grain',
                                           enterprises.today(self.conn)))
        other=self.owner()
        self.assertFalse(core.seller_allowed(self.conn,field,other['id'],'grain',
                                            enterprises.today(self.conn)))

    def test_purchase_rejects_foreign_buyer(self):
        seller=self.owner();buyer=self.owner();outsider=self.owner()
        field=self.enterprise(seller,'field',recipe='field_grain',stock=[('grain',100,70)])
        mill=self.enterprise(buyer,'mill',recipe='mill_flour')
        self.policy(seller,field)
        body={'buyer_enterprise_id':mill,'seller_enterprise_id':field,
              'product_id':'grain','quantity':10,'request_id':'p:'+uuid4().hex}
        with patch('server.sales.api.authenticate',return_value=outsider):
            self.assertEqual(api.purchase(body,{'conn':self.conn,'settings':self.flags})[0],404)

    def test_api_purchase_disabled(self):
        actor=self.owner()
        with patch('server.sales.api.authenticate',return_value=actor):
            self.assertEqual(api.purchase({}, {'conn':self.conn,'settings':{}})[0],404)

    def test_api_contract_disabled(self):
        actor=self.owner()
        with patch('server.sales.api.authenticate',return_value=actor):
            self.assertEqual(api.contract({}, {'conn':self.conn,'settings':{}})[0],404)

    def test_policy_pending_change_does_not_erase_original(self):
        actor=self.owner();field=self.enterprise(actor,'field',recipe='field_grain')
        self.policy(actor,field,mode='public')
        self.assertIsNone(core.current_policy(self.conn,field,'grain',enterprises.today(self.conn)))
        self.assertEqual(core.pending_policy(self.conn,field,'grain')['mode'],'public')

    def test_reliability_shipped_to_ordered(self):
        actor=self.owner();field=self.enterprise(actor,'field',recipe='field_grain')
        day=enterprises.today(self.conn)
        self.conn.execute('INSERT INTO sales_reliability_30d '
                          '(enterprise_id,product_id,day_index,ordered,fulfilled) '
                          'VALUES(%s,%s,%s,100,75)',(field,'grain',day))
        self.assertEqual(core.reliability(self.conn,field,'grain',day),750)

    def test_daily_not_enabled(self):
        actor=self.owner();field=self.enterprise(actor,'field',recipe='field_grain')
        ctx=self.ctx(actor,field);ctx['settings']={}
        with patch('server.sales.api.authenticate',return_value=actor):
            self.assertEqual(api.daily({},ctx)[0],404)

    def test_policy_invites_unknown_owner_rejected(self):
        seller=self.owner();field=self.enterprise(seller,'field',recipe='field_grain')
        self.assertEqual(self.policy(seller,field,mode='invited',
                         invited_owner_ids=[2**62])[0],400)

    def test_policy_version_increments_after_effective_day(self):
        seller=self.owner();field=self.enterprise(seller,'field',recipe='field_grain')
        status,first=self.policy(seller,field)
        self.assertEqual(status,200)
        self.conn.execute('''INSERT INTO game_ticks(day_index,completed)
            VALUES(%s,true) ON CONFLICT(day_index) DO UPDATE SET completed=true''',
            (first['effective_day'],))
        ctx=self.ctx(seller,field)
        payload={'mode':'mixed','reserve_bp':5000,'price':25,
                 'expected_version':first['version'],'request_id':'pol:'+uuid4().hex}
        with patch('server.sales.api.authenticate',return_value=seller):
            status,next_policy=api.policy_put(payload,ctx)
        self.assertEqual(status,200,next_policy)
        self.assertEqual(next_policy['version'],2)
        self.assertEqual(next_policy['effective_day'],enterprises.today(self.conn)+1)

    def test_private_mode_blocks_external_buyer(self):
        seller=self.owner();buyer=self.owner()
        field=self.enterprise(seller,'field',recipe='field_grain')
        self.policy(seller,field,mode='private')
        day=enterprises.today(self.conn)+1
        self.assertFalse(core.seller_allowed(self.conn,field,buyer['id'],'grain',day))
        self.assertTrue(core.seller_allowed(self.conn,field,seller['id'],'grain',day))

    def test_sales_day_receipt_no_duplicate(self):
        core.clear_day(self.conn,100001,self.flags)
        core.clear_day(self.conn,100001,self.flags)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM sales_day_receipts '
                          'WHERE day_index=%s',(100001,)).fetchone()[0],1)

    def test_purchase_idempotency_different_quantity_conflict(self):
        seller=self.owner();buyer=self.owner()
        field=self.enterprise(seller,'field',recipe='field_grain',stock=[('grain',100,80)])
        mill=self.enterprise(buyer,'mill',recipe='mill_flour')
        _,policy=self.policy(seller,field)
        self.conn.execute('''INSERT INTO game_ticks(day_index,completed) VALUES(%s,true)
            ON CONFLICT(day_index) DO UPDATE SET completed=true''',(policy['effective_day'],))
        ctx={'conn':self.conn,'settings':self.flags}
        payload={'buyer_enterprise_id':mill,'seller_enterprise_id':field,
                 'product_id':'grain','quantity':10,'request_id':'buy:'+uuid4().hex}
        with patch('server.sales.api.authenticate',return_value=buyer):
            self.assertEqual(api.purchase(payload,ctx)[0],201)
            self.assertEqual(api.purchase({**payload,'quantity':11},ctx)[0],409)

    def test_contract_blocks_transition_to_private(self):
        seller=self.owner();buyer=self.owner()
        field=self.enterprise(seller,'field',recipe='field_grain',stock=[('grain',100,80)])
        mill=self.enterprise(buyer,'mill',recipe='mill_flour')
        day=enterprises.today(self.conn)
        data={'seller_enterprise_id':field,'buyer_enterprise_id':mill,
              'product_id':'grain','volume':10,'start_day':day,'end_day':day+3,
              'price':25,'request_id':'ct:'+uuid4().hex}
        with patch('server.sales.api.authenticate',return_value=seller):
            self.assertEqual(api.contract(data,{'conn':self.conn,'settings':self.flags})[0],201)
        self.assertEqual(self.policy(seller,field,mode='private')[0],409)

    def test_contract_reserve_prevents_public_sale(self):
        seller=self.owner();buyer=self.owner()
        field=self.enterprise(seller,'field',recipe='field_grain',stock=[('grain',100,80)])
        mill=self.enterprise(buyer,'mill',recipe='mill_flour')
        day=enterprises.today(self.conn)
        data={'seller_enterprise_id':field,'buyer_enterprise_id':mill,
              'product_id':'grain','volume':80,'start_day':day,'end_day':day+3,
              'price':25,'request_id':'ct:'+uuid4().hex}
        with patch('server.sales.api.authenticate',return_value=seller):
            self.assertEqual(api.contract(data,{'conn':self.conn,'settings':self.flags})[0],201)
        self.assertEqual(core.reserve_for_contracts(self.conn,field,'grain',day),80)
        self.assertEqual(core.offer_quantities(100,'public',0,80),(0,80,20))

    def test_stock_not_negative_after_rejected_purchase(self):
        seller=self.owner();buyer=self.owner()
        field=self.enterprise(seller,'field',recipe='field_grain',stock=[('grain',1,80)])
        mill=self.enterprise(buyer,'mill',recipe='mill_flour')
        _,policy=self.policy(seller,field)
        self.conn.execute('''INSERT INTO game_ticks(day_index,completed) VALUES(%s,true)
            ON CONFLICT(day_index) DO UPDATE SET completed=true''',(policy['effective_day'],))
        payload={'buyer_enterprise_id':mill,'seller_enterprise_id':field,
                 'product_id':'grain','quantity':2,'request_id':'buy:'+uuid4().hex}
        with patch('server.sales.api.authenticate',return_value=buyer):
            self.assertEqual(api.purchase(payload,{'conn':self.conn,'settings':self.flags})[0],409)
        self.assertEqual(self.qty(field,'grain'),1)

    def test_sales_daily_shows_only_owner(self):
        seller=self.owner();field=self.enterprise(seller,'field',recipe='field_grain')
        ctx=self.ctx(seller,field)
        with patch('server.sales.api.authenticate',return_value=seller):
            status,data=api.daily({},ctx)
        self.assertEqual(status,200)
        self.assertEqual(data['enterprise_id'],field)
