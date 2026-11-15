"""EX-04 municipal tender ranking, city budgets and NPC/player parity."""
import city
import city_catalog
import contractors
import economy
import game_server
import tenders
from test_ex_03_04_helpers import SQLiteEXCase,T0,rid

DAY=86400

class TenderTests(SQLiteEXCase):
    def setUp(self):
        super().setUp()
        with game_server.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            city.set_mayor(db,"?","alice","Mayor Alice",0,now=T0)

    def create_tender(self,key="school",x=1,y=1,months=2):
        return self.call(tenders.create,"alice",
                         {"object_id":key,"x":x,"y":y,"months":months,"request_id":rid()})

    def test_small_public_order_uses_npc_and_city_budget(self):
        self.fund(economy.CITY,1000000)
        status,t=self.create_tender(key="bus_stop")
        self.assertEqual(status,201,t)
        self.assertEqual(t["procedure"],"direct")
        row=self.query("SELECT status,winner,project_id FROM tenders WHERE id=?",(t["tender_id"],))[0]
        self.assertEqual(row[0],"awarded")
        self.assertTrue(row[1].startswith("npc:"))
        self.assertIsNotNone(row[2])
        self.assertEqual(self.query("SELECT owner FROM construction_projects WHERE id=?",(row[2],))[0][0],economy.CITY)
        self.assertEqual(self.query("SELECT COUNT(*) FROM ledger_tx WHERE kind='construction_reserve'")[0][0],1)
        self.check_ledger()

    def test_small_order_retries_when_budget_arrives(self):
        status,t=self.create_tender(key="bus_stop")
        self.assertEqual(status,201,t)
        self.assertEqual(self.query("SELECT status FROM tenders WHERE id=?",(t["tender_id"],))[0][0],"pending_funding")
        self.fund(economy.CITY,1000000)
        result=self.run_tx(tenders.monthly,1,now=T0+DAY)
        self.assertEqual(result["awarded"],1,result)
        self.assertEqual(self.query("SELECT status FROM tenders WHERE id=?",(t["tender_id"],))[0][0],"awarded")
        self.check_ledger()

    def test_competitive_bid_better_than_npc_wins(self):
        self.fund(economy.CITY,40_000_000)
        s,t=self.create_tender()
        self.assertEqual(s,201,t)
        self.assertEqual(t["procedure"],"competitive")
        s,c=self.call(contractors.register,"bob",
                      {"name":"Честная стройка","capacity":2,"request_id":rid()})
        self.assertEqual(s,201,c)
        offer=t["budget"]*9//10
        s,b=self.call(tenders.bid,"bob",
                  {"tender_id":t["tender_id"],"contractor_id":c["contractor_id"],
                   "price":offer,"months":2,"request_id":rid()})
        self.assertEqual(s,201,b)
        s,b=self.call(tenders.bid,"bob",
                  {"tender_id":t["tender_id"],"contractor_id":c["contractor_id"],
                   "price":offer+1,"months":2,"request_id":rid()})
        self.assertEqual(b["error"],"offer_must_improve")
        result=self.run_tx(tenders.monthly,2,now=T0+2*DAY)
        self.assertEqual(result["awarded"],1,result)
        selected=self.query("SELECT winner,winning_price,winning_months,project_id FROM tenders WHERE id=?",
                            (t["tender_id"],))[0]
        self.assertEqual(selected[:3],(c["contractor_id"],offer,2))
        self.assertEqual(self.query("SELECT total_cost FROM construction_projects WHERE id=?",
                                    (selected[3],))[0][0],offer)
        self.check_ledger()

    def test_npc_bids_obey_budget_and_tender_deadline(self):
        self.fund(economy.CITY,40_000_000)
        s,t=self.create_tender()
        self.assertEqual(s,201,t)
        npc=self.query("SELECT bidder,price FROM tender_bids WHERE tender_id=?",(t["tender_id"],))
        self.assertGreater(len(npc),0)
        self.assertTrue(all(name.startswith("npc:") and price<=t["budget"] for name,price in npc))
        result=self.run_tx(tenders.monthly,1,now=T0+DAY)
        self.assertEqual(result["awarded"],0,result)
        self.assertEqual(self.query("SELECT status FROM tenders WHERE id=?",(t["tender_id"],))[0][0],"open")
        result=self.run_tx(tenders.monthly,2,now=T0+2*DAY)
        self.assertEqual(result["awarded"],1,result)
        self.assertTrue(self.query("SELECT winner FROM tenders WHERE id=?",(t["tender_id"],))[0][0].startswith("npc:"))
        self.check_ledger()

    def test_mayor_cannot_bid_in_own_procurement(self):
        self.fund(economy.CITY,40_000_000)
        s,t=self.create_tender()
        self.assertEqual(s,201,t)
        s,c=self.call(contractors.register,"alice",
                      {"name":"МэрСтрой","capacity":1,"request_id":rid()})
        self.assertEqual(s,201,c)
        offer=t["budget"]*9//10
        s,body=self.call(tenders.bid,"alice",
                   {"tender_id":t["tender_id"],"contractor_id":c["contractor_id"],
                    "price":offer,"months":2,"request_id":rid()})
        self.assertEqual(s,403,body)
        self.assertEqual(body["error"],"conflict_of_interest")
        self.check_ledger()

    def test_no_bids_does_not_spend_city_budget(self):
        with game_server.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE contractors SET active=0 WHERE owner LIKE 'npc:%'")
        self.fund(economy.CITY,40_000_000)
        status,t=self.create_tender()
        self.assertEqual(status,201,t)
        before=self.query("SELECT balance FROM wallets WHERE account=?",
                          (economy.player_account(economy.CITY),))[0][0]
        self.run_tx(tenders.monthly,2,now=T0+2*DAY)
        self.assertEqual(self.query("SELECT status FROM tenders WHERE id=?",(t["tender_id"],))[0][0],"no_bids")
        after=self.query("SELECT balance FROM wallets WHERE account=?",
                         (economy.player_account(economy.CITY),))[0][0]
        self.assertEqual(before,after)
        self.check_ledger()
