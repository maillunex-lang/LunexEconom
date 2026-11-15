"""EX-03 land integration, transfers, zoning, leases and legacy migration."""
import concurrent.futures
import os
from unittest import mock

import city
import clock
import construction_projects
import economy
import game_server
import land
from test_ex_03_04_helpers import SQLiteEXCase, T0, rid

class LandTests(SQLiteEXCase):
    def test_two_competing_buyers_one_parcel_and_one_debit(self):
        self.fund("alice")
        self.fund("bob")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            res=list(pool.map(lambda name:self.buy(name),("alice","bob")))
        self.assertEqual(sorted(s for s,_ in res),[201,409],res)
        self.assertEqual(self.query("SELECT COUNT(*) FROM ledger_tx WHERE kind='land_buy'")[0][0],1)
        self.assertEqual(self.query("SELECT COUNT(*) FROM land_parcels WHERE id='0:0'")[0][0],1)
        self.check_ledger()

    def test_request_replay_no_double_charge_and_price_ceiling(self):
        self.fund("alice")
        request=rid()
        status,result=self.buy("alice",r=request)
        self.assertEqual(status,201,result)
        replay=self.buy("alice",r=request)
        self.assertEqual(replay,(200,result))
        self.assertEqual(self.query("SELECT COUNT(*) FROM ledger_tx WHERE kind='land_buy'")[0][0],1)
        self.assertEqual(self.call(land.buy,"bob",{"px":0,"py":0,"request_id":rid()})[0],409)
        self.assertEqual(self.call(land.buy,"alice",{"px":1,"py":0,
                     "max_price":1,"request_id":rid()})[1]["error"],"price_changed")
        self.check_ledger()

    def test_lease_first_month_not_charged_twice(self):
        self.fund("alice")
        status,res=self.call(land.lease,"alice",{"px":1,"py":0,"months":3,"request_id":rid()})
        self.assertEqual(status,201,res)
        amount=res["rent_month"]
        def monthly(db,ph,month,now):
            return land.monthly(db,ph,month,now)
        result=self.run_tx(monthly,0,now=T0)
        self.assertEqual(result["rent"],0)
        result=self.run_tx(monthly,1,now=T0+86400)
        self.assertEqual(result["rent"],amount)
        result=self.run_tx(monthly,1,now=T0+86400)
        self.assertEqual(result["rent"],0)
        result=self.run_tx(monthly,3,now=T0+3*86400)
        self.assertEqual(result["expired"],1)
        self.assertIsNone(self.query("SELECT tenant FROM land_parcels WHERE id='1:0'")[0][0])
        self.assertEqual(self.query("SELECT COUNT(*) FROM ledger_tx WHERE kind='land_rent'")[0][0],2)
        self.check_ledger()

    def test_vacant_land_tax_debt_is_recovered(self):
        self.fund("alice")
        s,res=self.buy()
        self.assertEqual(s,201,res)
        with game_server.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current=economy.balance(db,"?","alice")
            economy.post(db,"?","test_withdraw","deplete test wallet",
                         [(economy.player_account("alice"),-current),(economy.TREASURY,current)],T0)
        self.run_tx(land.monthly,1,now=T0+86400)
        owed=self.query("SELECT amount FROM land_tax_arrears WHERE parcel_id='0:0'")[0][0]
        self.assertGreater(owed,0)
        self.fund("alice",extra=10_000)
        self.run_tx(land.monthly,2,now=T0+2*86400)
        self.assertEqual(self.query("SELECT amount FROM land_tax_arrears WHERE parcel_id='0:0'")[0][0],0)
        self.check_ledger()

    def test_mayor_approves_zone_change_but_not_without_application(self):
        self.fund("alice")
        self.assertEqual(self.buy()[0],201)
        with game_server.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            city.set_mayor(db,"?","bob","Mayor Bob",0,now=T0)
        req=self.call(land.rezone,"alice",{"px":0,"py":0,"zone":"industrial","request_id":rid()})
        self.assertEqual(req[0],201,req)
        self.assertEqual(self.call(land.decide_rezone,"alice",
                         {"application_id":req[1]["application_id"],"approve":True,"request_id":rid()})[0],403)
        status,ok=self.call(land.decide_rezone,"bob",
                           {"application_id":req[1]["application_id"],"approve":True,"request_id":rid()})
        self.assertEqual(status,200,ok)
        self.assertEqual(self.query("SELECT zone FROM land_parcels WHERE id='0:0'")[0][0],"industrial")

    def test_buyback_requires_authenticated_landholder_consent(self):
        self.fund("alice")
        self.fund(economy.CITY,20_000_000)
        self.assertEqual(self.buy()[0],201)
        with game_server.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            city.set_mayor(db,"?","bob","Mayor Bob",0,now=T0)
        payload={"px":0,"py":0,"request_id":rid(),"owner_consent":"alice"}
        self.assertEqual(self.call(land.buyback,"bob",payload)[1]["error"],
                         "buyback_requires_owner_authorization")
        self.assertEqual(self.call(land.consent_buyback,"bob",{"px":0,"py":0,"request_id":rid()})[0],403)
        self.assertEqual(self.call(land.consent_buyback,"alice",{"px":0,"py":0,"request_id":rid()})[0],201)
        status,body=self.call(land.buyback,"bob",payload)
        self.assertEqual(status,201,body)
        self.assertEqual(self.query("SELECT owner FROM land_parcels WHERE id='0:0'")[0][0],"municipal:ufa")
        self.check_ledger()

    def test_existing_building_migration_preserves_owner_and_cells(self):
        with mock.patch.dict(os.environ,{"LAND_ENABLED":"0"}):
            s,res=game_server.build("alice",{"kind":"farm","x":8,"y":10,"request_id":rid()})
        self.assertEqual(s,201,res)
        original=self.query("SELECT id,owner,x,y FROM buildings")[0]
        with game_server.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            migrated=land.migrate_existing(db,"?")
            self.assertGreater(migrated,0)
        px,py=land.parcel_for_cell(8,10)
        self.assertEqual(self.query("SELECT owner FROM land_parcels WHERE id=?",(f"{px}:{py}",))[0][0],"alice")
        self.assertEqual(self.query("SELECT id,owner,x,y FROM buildings")[0],original)
        self.check_ledger()

    def test_feature_disabled_changes_no_existing_build_economy(self):
        with mock.patch.dict(os.environ,{"LAND_ENABLED":"0","CONSTRUCTION_PROJECTS_ENABLED":"0"}):
            status,res=game_server.build("alice",{"kind":"farm","x":8,"y":10,"request_id":rid()})
            self.assertEqual(status,201,res)
            self.assertEqual(res["cost"],120_000+5000*res["road_cells"])
        self.check_ledger()
