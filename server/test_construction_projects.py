"""EX-04 construction phase payments, inventory/market shortages and commissioning."""
import os
from unittest import mock

import construction_projects as projects
import construction_stages
import contractors
import economy
import game_server
import goods_catalog
import land
from test_ex_03_04_helpers import SQLiteEXCase,T0,rid

DAY=86400

class ProjectTests(SQLiteEXCase):
    def setUp(self):
        super().setUp()
        self.fund("alice",extra=16_000_000)
        self.assertEqual(self.buy("alice")[0],201)

    def create(self,x=1,y=1,owner="alice",key="house_wood",request_id=None,**kwargs):
        return self.call(projects.create,owner,
                         {"object_id":key,"x":x,"y":y,
                          "request_id":request_id or rid(),**kwargs})

    def seed_market(self,month=0,supply=10000):
        with game_server.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for good in goods_catalog.GOODS:
                db.execute("""INSERT INTO market_prices(product,month_index,price,supply,demand)
                          VALUES(?,?,?,?,?)""",
                          (good.id,month,good.reference_price,supply,100))

    def progress(self,month):
        return self.run_tx(projects.monthly,month,now=T0+DAY*month)

    def test_four_stages_commission_housing_and_ledger(self):
        self.seed_market()
        status,created=self.create()
        self.assertEqual(status,201,created)
        pid=created["project_id"]
        self.assertEqual(construction_stages.STAGES_PER_MONTH,6)
        self.assertEqual(self.query("SELECT COUNT(*) FROM building_ops WHERE object_id=?",(pid,))[0][0],0)
        self.assertEqual(self.progress(1)["completed"],1)
        data=self.query("SELECT status,stage_index FROM construction_projects WHERE id=?",(pid,))[0]
        self.assertEqual(data,("complete",4))
        self.assertEqual(self.query("SELECT owner,capacity FROM construction_housing_supply WHERE project_id=?",(pid,))[0],
                         ("alice",4))
        changes=self.query("""SELECT payload FROM events WHERE kind='building_created'
                               AND payload LIKE ?""",('%'+pid+'%',))
        self.assertEqual(len(changes),5)
        self.assertEqual(self.query("SELECT balance FROM wallets WHERE account=?",
                                     ("system:project:"+pid,))[0][0],0)
        self.check_ledger()

    def test_shortage_delays_without_spending_reserved_funds_twice(self):
        status,created=self.create()
        self.assertEqual(status,201,created)
        pid=created["project_id"]
        self.assertEqual(self.progress(1)["delayed"],1)
        p=self.query(
           "SELECT status,stage_index,delay_reason FROM construction_projects WHERE id=?",(pid,))[0]
        self.assertEqual(p,("delayed",0,"market_quote_unavailable"))
        self.assertEqual(self.query("SELECT COALESCE(SUM(used),0) FROM project_materials WHERE project_id=?",(pid,))[0][0],0)
        self.seed_market(month=0)
        result=self.progress(2)
        self.assertEqual(result["completed"],1,result)
        self.assertEqual(self.progress(2)["completed"],0)
        # Four stage-specific transfers, each balanced and idempotent.
        self.assertEqual(self.query("SELECT COUNT(*) FROM ledger_tx WHERE kind='construction_material'")[0][0],4)
        self.check_ledger()

    def test_competing_projects_cannot_exceed_material_supply(self):
        self.seed_market(month=0,supply=32)
        a=self.create(x=1,y=1)
        b=self.create(x=1,y=2)
        self.assertEqual(a[0],201,a)
        self.assertEqual(b[0],201,b)
        result=self.progress(1)
        self.assertEqual(result["completed"],1,result)
        self.assertEqual(result["delayed"],1,result)
        self.assertEqual(self.query("""SELECT qty FROM construction_market_purchases
                     WHERE product='timber' AND month_index=1""")[0][0],32)
        self.seed_market(month=2,supply=32)
        result=self.progress(2)
        self.assertEqual(result["completed"],1,result)
        self.assertEqual(self.query("SELECT COUNT(*) FROM construction_projects WHERE status='complete'")[0][0],2)
        self.check_ledger()

    def test_cancel_releases_cells_and_refunds_unused_escrow(self):
        status,p=self.create()
        self.assertEqual(status,201,p)
        pid=p["project_id"]
        status,done=self.call(projects.cancel,"alice",{"project_id":pid,"request_id":rid()})
        self.assertEqual(status,200,done)
        self.assertEqual(done["refund"]+done["cancellation_fee"],p["cost"])
        self.assertEqual(self.query("SELECT COUNT(*) FROM buildings WHERE id=?",(pid,))[0][0],0)
        self.assertEqual(self.query("SELECT COUNT(*) FROM cells WHERE object_id=?",(pid,))[0][0],0)
        self.assertEqual(self.query("SELECT status FROM construction_projects WHERE id=?",(pid,))[0][0],"cancelled")
        self.assertEqual(self.call(projects.cancel,"alice",{"project_id":pid,"request_id":rid()})[0],409)
        self.check_ledger()

    def test_requires_land_ownership_and_preserves_old_build_when_disabled(self):
        self.assertEqual(self.create(x=7,y=1)[1]["error"],"land_not_owned")
        with mock.patch.dict(os.environ,{"LAND_ENABLED":"0"}):
            self.assertEqual(self.create()[1]["error"],"land_feature_required")
        self.check_ledger()

    def test_request_idempotency_does_not_duplicate_project(self):
        self.seed_market()
        request=rid()
        first=self.create(request_id=request)
        self.assertEqual(first[0],201,first)
        self.assertEqual(self.create(request_id=request),(200,first[1]))
        self.assertEqual(self.query("SELECT COUNT(*) FROM construction_projects")[0][0],1)
        self.assertEqual(self.query("SELECT COUNT(*) FROM ledger_tx WHERE kind='construction_reserve'")[0][0],1)
        self.check_ledger()

    def test_contractor_capacity_and_stage_payments(self):
        self.seed_market()
        status,c=self.call(contractors.register,"bob",
                           {"name":"СтройБоб","capacity":1,"request_id":rid()})
        self.assertEqual(status,201,c)
        cid=c["contractor_id"]
        a=self.create(contractor_id=cid)
        self.assertEqual(a[0],201,a)
        b=self.create(x=1,y=2,contractor_id=cid)
        self.assertEqual(b[1]["error"],"contractor_unavailable")
        self.assertEqual(self.progress(1)["completed"],1)
        self.assertEqual(self.query("SELECT status FROM contractor_orders WHERE project_id=?",(a[1]["project_id"],))[0][0],"complete")
        self.assertGreater(self.query("SELECT balance FROM wallets WHERE account=?",
                                      (economy.player_account("bob"),))[0][0],0)
        self.assertEqual(self.create(x=1,y=2,contractor_id=cid)[0],201)
        self.check_ledger()

    def test_wear_and_repair_are_balanced(self):
        self.seed_market()
        s,p=self.create()
        self.assertEqual(s,201,p)
        self.progress(1)
        self.progress(2)
        before=self.query("SELECT condition_permille FROM construction_projects WHERE id=?",
                          (p["project_id"],))[0][0]
        self.assertLess(before,1000)
        status,repaired=self.call(projects.repair,"alice",
                        {"project_id":p["project_id"],"request_id":rid()},now=T0+2*DAY)
        self.assertEqual(status,201,repaired)
        self.assertEqual(self.query("SELECT condition_permille FROM construction_projects WHERE id=?",
                                    (p["project_id"],))[0][0],1000)
        self.check_ledger()
