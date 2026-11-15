"""V2-06: isolated PostgreSQL retail, inventory, VAT, actual M1 construction."""
import os
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from server import db
from server.game_server import create_app
from server.ledger.api import account, transfer, reconcile
from server.enterprises import core as enterprise
from server.supply import api as supply_api, core as supply
from server.market import core as market
from server.retail import core, api
from server.world import core as world, api as world_api

DSN=os.getenv('LUNEX_TEST_DATABASE_URL')
FLAGS={
    'supply_transport_rub_per_km_unit_draft':1,
    'supply_port_city_draft':'ufa',
    'supply_port_price_permille_draft':1000,
    'supply_port_duty_bp_draft':500,
    'supply_port_fallback_draft':False,
}


@unittest.skipUnless(DSN,'isolated PostgreSQL 16 DSN required')
class RetailPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=create_app(DSN)

    @classmethod
    def tearDownClass(cls):
        cls.app.close()

    def setUp(self):
        self.conn=db.connect(DSN)
        self.serial=0
        self.day=int(self.conn.execute(
            'SELECT GREATEST(COALESCE((SELECT max(day_index) FROM retail_receipts),-1),'
            ' COALESCE((SELECT max(day_index) FROM game_ticks),-1))').fetchone()[0])+100
        self.market=account(self.conn,'system:market')
        self.treasury=account(self.conn,'system:treasury')

    def tearDown(self):
        self.conn.rollback()
        self.conn.close()

    def owner(self,money=2000000):
        name='ret'+uuid4().hex[:12]
        oid=self.conn.execute("""INSERT INTO accounts(username,email,password_hash,role)
            VALUES(%s,%s,'hash','player') RETURNING id""",(name,name+'@example.test')).fetchone()[0]
        wallet=account(self.conn,'player:'+name,'player',oid)
        if money:
            transfer(self.conn,'retail:test:'+uuid4().hex,self.treasury,wallet,money)
        return {'id':oid,'username':name,'wallet':wallet}

    def store(self, owner, stock=(), building='grocery_store', city='ufa', stage=4):
        self.serial+=1
        n=90000000+owner['id']*1000+self.serial
        self.conn.execute("""INSERT INTO world_parcels(px,py,city_id,owner_kind,owner_ref)
            VALUES(%s,%s,%s,'player',%s)""",(n,n,city,str(owner['id'])))
        x=world.CITIES[city]['x']
        y=world.CITIES[city]['y']
        tx=transfer(self.conn,'retail:fixture:'+uuid4().hex,self.treasury,owner['wallet'],1)
        eid=self.conn.execute("""INSERT INTO enterprises
          (owner_id,building_id,px,py,x,y,width,height,city_id,name,build_cost,
           build_days,upkeep_month,jobs,storage_capacity,started_day,stage,
           recipe_id,build_request_id,build_transfer_id)
          VALUES(%s,%s,%s,%s,%s,%s,1,1,%s,'retail fixture',1,
                 1,0,0,4000,0,%s,NULL,%s,%s) RETURNING id""",
          (owner['id'],building,n,n,x,y,city,stage,'retail:build:'+uuid4().hex,tx)).fetchone()[0]
        for good,qty,quality in stock:
            enterprise.adjust(self.conn,eid,good,qty,quality)
        return eid

    def ctx(self,eid):
        return {'conn':self.conn,'path_params':{'id':str(eid)},'query':{}}

    def cell(self, idx=0,good='bread',price=90,minimum=100,slot=None):
        return dict(cell_index=idx,product_id=good,price=price,min_stock=minimum,supply_link_slot=slot)

    def configure(self,owner,eid,cells):
        with patch('server.retail.api.authenticate',return_value=owner):
            status,result=api.put_cells({'cells':cells},self.ctx(eid))
        self.assertEqual(status,200,result)

    def test_owner_atomic_validation_and_ratings(self):
        a,b=self.owner(),self.owner()
        eid=self.store(a,stock=[('bread',100,50)])
        self.configure(a,eid,[self.cell()])
        with patch('server.retail.api.authenticate',return_value=b):
            self.assertEqual(api.get_cells({},self.ctx(eid))[0],404)
            self.assertEqual(api.put_cells({'cells':[]},self.ctx(eid))[0],404)
            self.assertEqual(api.sales({},self.ctx(eid))[0],404)
        with patch('server.retail.api.authenticate',return_value=a):
            for bad in ([self.cell(),self.cell()],[self.cell(good='grain')],
                        [self.cell(price=0)],[self.cell(idx=10)],
                        [self.cell(price=True)]):
                code,_=api.put_cells({'cells':bad},self.ctx(eid))
                self.assertEqual(code,400)
            self.assertEqual(len(api.get_cells({},self.ctx(eid))[1]['cells']),1)
            self.assertEqual(api.put_cells({'cells':[self.cell(slot=1)]},self.ctx(eid))[0],400)
        code,result=api.ratings({},{'conn':self.conn,
            'query':{'city':['ufa'],'good':['bread']}})
        self.assertEqual(code,200,result)
        self.assertEqual(result['ratings'][0]['rating'],70)

    def test_competitors_split_small_city_demand_by_squared_appeal(self):
        expensive_owner,cheap_owner=self.owner(),self.owner()
        expensive=self.store(expensive_owner,stock=[('bread',500,50)])
        cheap=self.store(cheap_owner,stock=[('bread',500,50)])
        self.configure(expensive_owner,expensive,[self.cell(price=135,minimum=10)])
        self.configure(cheap_owner,cheap,[self.cell(price=90,minimum=10)])
        # Demand of a realistic-sized city dwarfing shop inventory obscures the
        # allocation; cap *this test city's population only* under rollback.
        self.conn.execute("UPDATE world_cities SET population=100 WHERE id='ufa'")
        core.advance_day(self.conn,self.day)
        records=dict(self.conn.execute("""SELECT enterprise_id,quantity FROM retail_sales_daily
                 WHERE day_index=%s""",(self.day,)).fetchall())
        self.assertGreater(records[cheap],records[expensive])
        self.assertGreater(records[expensive],0)
        self.assertLess(sum(records.values()),1000)
        self.assertEqual(enterprise.stock(self.conn,cheap)['bread']['quantity'],
                         500-records[cheap])
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_supply_link_retail_and_day(self):
        a=self.owner()
        bakery=self.store(a,building='bakery',stock=[('bread',50,50)])
        self.conn.execute("UPDATE enterprises SET recipe_id='bakery_bread' WHERE id=%s",(bakery,))
        shop=self.store(a)
        with patch('server.supply.api.authenticate',return_value=a):
            link={'source_type':'enterprise','source_enterprise_id':bakery,
                  'share':1000,'priority':1,'max_price':90,'min_quality':0}
            status,result=supply_api.put({'inputs':{'bread':[link]}},self.ctx(shop))
            self.assertEqual(status,200,result)
        self.configure(a,shop,[self.cell(minimum=50,slot=1)])
        self.assertEqual(supply._need(self.conn,(shop,a['id'],None,'ufa',4,True,4000)),{'bread':50})
        supply.links_day(self.conn,self.day,FLAGS)
        self.assertEqual(enterprise.stock(self.conn,shop)['bread']['quantity'],50)
        core.advance_day(self.conn,self.day)
        sold=self.conn.execute('SELECT quantity,revenue FROM retail_sales_daily WHERE enterprise_id=%s',(shop,)).fetchone()
        self.assertEqual(sold,(50,4500))
        self.assertTrue(self.conn.execute('SELECT 1 FROM retail_alerts WHERE enterprise_id=%s',(shop,)).fetchone())
        self.assertTrue(reconcile(self.conn)['ok'])
        before=self.conn.execute('SELECT count(*) FROM ledger_transfers').fetchone()[0]
        core.advance_day(self.conn,self.day)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM ledger_transfers').fetchone()[0],before)
        self.assertEqual(enterprise.stock(self.conn,shop)['bread']['quantity'],0)

    def test_split_stock_quality_price_idempotence_and_vat(self):
        a,b=self.owner(),self.owner()
        good=self.store(a,stock=[('bread',100,80)])
        weak=self.store(b,stock=[('bread',100,20)])
        self.configure(a,good,[self.cell(price=90,minimum=150)])
        self.configure(b,weak,[self.cell(price=135,minimum=150)])
        ratings=api.ratings({},dict(conn=self.conn,query={'city':['ufa'],'good':['bread']}))[1]['ratings']
        self.assertGreater(ratings[0]['rating'],ratings[1]['rating'])
        core.advance_day(self.conn,self.day)
        numbers=self.conn.execute("""SELECT enterprise_id,quantity,revenue FROM retail_sales_daily
          WHERE day_index=%s ORDER BY enterprise_id""",(self.day,)).fetchall()
        self.assertEqual([r[1] for r in numbers],[100,100])
        self.assertEqual([r[2] for r in numbers],[9000,13500])
        self.assertTrue(reconcile(self.conn)['ok'])
        core.advance_day(self.conn,self.day)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM retail_sales_daily WHERE day_index=%s',(self.day,)).fetchone()[0],2)
        core.close_month(self.conn,self.day//30 if self.day%30==0 else self.day//30+1)
        # The monthly interval intentionally may exclude this fixture day.
        month=(self.day-1)//30+1
        core.close_month(self.conn,month)
        self.assertEqual(self.conn.execute('SELECT revenue FROM enterprise_month_reports WHERE enterprise_id=%s AND month_index=%s',(good,month)).fetchone()[0],9000)
        receipt=self.conn.execute('SELECT revenue,vat,paid FROM retail_month_receipts WHERE enterprise_id=%s AND month_index=%s',(good,month)).fetchone()
        self.assertEqual(receipt,(9000,819,True))
        before=self.conn.execute('SELECT count(*) FROM ledger_transfers WHERE request_id=%s',(f'retail:vat:{good}:{month}',)).fetchone()[0]
        core.close_month(self.conn,month)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM ledger_transfers WHERE request_id=%s',(f'retail:vat:{good}:{month}',)).fetchone()[0],before)
        self.assertEqual(before,1)
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_no_player_overdraft_on_vat_due(self):
        owner=self.owner(money=0)
        eid=self.store(owner,stock=[('bread',100,50)])
        self.configure(owner,eid,[self.cell()])
        core.advance_day(self.conn,self.day)
        # Spend all receipts so the VAT cannot be paid in this month.
        balance=self.conn.execute('SELECT balance FROM ledger_accounts WHERE id=%s',(owner['wallet'],)).fetchone()[0]
        transfer(self.conn,'retail:drain:'+uuid4().hex,owner['wallet'],self.treasury,balance)
        month=(self.day-1)//30+1
        core.close_month(self.conn,month)
        self.assertEqual(self.conn.execute('SELECT balance FROM ledger_accounts WHERE id=%s',(owner['wallet'],)).fetchone()[0],0)
        self.assertEqual(self.conn.execute('SELECT paid FROM retail_month_receipts WHERE enterprise_id=%s AND month_index=%s',(eid,month)).fetchone()[0],False)
        transfer(self.conn,'retail:replenish:'+uuid4().hex,self.treasury,owner['wallet'],1000)
        core.close_month(self.conn,month)
        self.assertEqual(self.conn.execute('SELECT paid FROM retail_month_receipts WHERE enterprise_id=%s AND month_index=%s',(eid,month)).fetchone()[0],True)
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_m1_real_construction_supply_and_sales_ten_days(self):
        # The owner supplies extra starting funds *only for this explicit test*
        # because four buildings cost 1.6m versus the 1m platform grant.
        owner=self.owner(2100000)
        # Anchor the actual construction day to this test's clock index.
        # Without this, place() reads day zero from an empty game_ticks table
        # while the isolated daily receipt tests use higher numbered days.
        self.conn.execute('INSERT INTO game_ticks(day_index,completed) VALUES(%s,true)',
                          (self.day-1,))
        choices=[
            ('field',13,2),
            ('mill',9,-2),
            ('bakery',10,-5),
            ('grocery_store',6,-2),
        ]
        ids={}
        from server.world import api as world_http
        purchased=set()
        with patch('server.world.api.authenticate',return_value=owner):
            for building,x,y in choices:
                px,py=x//6,y//6
                if (px,py) not in purchased:
                    status,result=world_http.buy(
                        {'px':px,'py':py,'request_id':'ret-land-'+uuid4().hex},
                        {'conn':self.conn})
                    self.assertEqual(status,201,result)
                    purchased.add((px,py))
                code,created=enterprise.place(self.conn,owner,'ret-build-'+uuid4().hex,
                                              building,px,py,x,y)
                self.assertEqual(code,201,created)
                ids[building]=created['id']
        with patch('server.supply.api.authenticate',return_value=owner):
            for buyer,product,seller in (
                    ('mill','grain','field'),('bakery','flour','mill'),
                    ('grocery_store','bread','bakery')):
                row={'source_type':'enterprise','source_enterprise_id':ids[seller],
                     'share':1000,'priority':1,'max_price':1000,'min_quality':0}
                code,result=supply_api.put({'inputs':{product:[row]}},self.ctx(ids[buyer]))
                self.assertEqual(code,200,result)
        self.configure(owner,ids['grocery_store'],
                       [self.cell(minimum=100,slot=1)])
        # Clock model: every day executes links, clearing, then retail and
        # production; production becomes available to the supply on next day.
        for day in range(self.day,self.day+10):
            supply.links_day(self.conn,day,FLAGS)
            supply.market_day(self.conn,day,FLAGS)
            core.advance_day(self.conn,day)
            enterprise.advance_day(self.conn,day)
        income=self.conn.execute('SELECT COALESCE(sum(revenue),0) FROM retail_sales_daily WHERE enterprise_id=%s',
                                 (ids['grocery_store'],)).fetchone()[0]
        self.assertGreater(income,0,{'income':income,'stores':ids})
        print(f'V2-06 M1 TEN DAYS: revenue={income} RUB, buildings={ids}')
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_unpaid_tax_retried_at_later_monthly_close(self):
        owner=self.owner(money=0)
        shop=self.store(owner,stock=[('bread',10,50)])
        self.configure(owner,shop,[self.cell()])
        core.advance_day(self.conn,self.day)
        balance=self.conn.execute('SELECT balance FROM ledger_accounts WHERE id=%s',
                                  (owner['wallet'],)).fetchone()[0]
        transfer(self.conn,'retail:drain:'+uuid4().hex,owner['wallet'],self.treasury,balance)
        month=(self.day-1)//30+1
        core.close_month(self.conn,month)
        self.assertEqual(self.conn.execute('SELECT paid FROM retail_month_receipts WHERE enterprise_id=%s AND month_index=%s',
                           (shop,month)).fetchone()[0],False)
        transfer(self.conn,'retail:fund-overdue:'+uuid4().hex,self.treasury,owner['wallet'],1000)
        core.close_month(self.conn,month+1)
        self.assertEqual(self.conn.execute('SELECT paid FROM retail_month_receipts WHERE enterprise_id=%s AND month_index=%s',
                           (shop,month)).fetchone()[0],True)
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_benchmark_200_cells(self):
        owner=self.owner(money=0)
        stores=[self.store(owner,stock=[('bread',200,50)]) for _ in range(25)]
        for eid in stores:
            self.configure(owner,eid,[self.cell(idx) for idx in range(8)])
        started=time.monotonic()
        core.advance_day(self.conn,self.day)
        seconds=time.monotonic()-started
        count=self.conn.execute('SELECT count(*) FROM retail_sales_daily WHERE day_index=%s',(self.day,)).fetchone()[0]
        self.assertEqual(count,200)
        for eid in stores:
            self.assertEqual(enterprise.stock(self.conn,eid)['bread']['quantity'],0)
            used=self.conn.execute('SELECT sum(quantity) FROM retail_sales_daily WHERE enterprise_id=%s AND day_index=%s',
                                   (eid,self.day)).fetchone()[0]
            self.assertEqual(used,200)
        self.assertTrue(reconcile(self.conn)['ok'])
        self.assertLess(seconds,90)
        print(f'V2-06 BENCHMARK: 200 cells, {seconds:.3f}s')
