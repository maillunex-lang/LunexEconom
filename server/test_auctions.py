"""EX-03 competitive auctions and escrow, including replay and auction bypass."""
import concurrent.futures

import city
import economy
import game_server
import land
from test_ex_03_04_helpers import SQLiteEXCase, T0, rid

class AuctionTests(SQLiteEXCase):
    def setUp(self):
        super().setUp()
        self.fund("bob",20_000_000)
        self.fund("carol",20_000_000)
        with game_server.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            city.set_mayor(db,"?","alice","Mayor Alice",0,now=T0)

    def start(self,px=1,py=0):
        return self.call(land.start_auction,"alice",
                         {"px":px,"py":py,"months":2,"request_id":rid()})

    def test_bids_escrow_refunds_close_winner(self):
        s,a=self.start()
        self.assertEqual(s,201,a)
        aid=a["auction_id"]
        first=a["start"]
        second=first+a["min_step"]
        initial_bob=self.query("SELECT balance FROM wallets WHERE account=?",
                               (economy.player_account("bob"),))[0][0]
        s,b=self.call(land.bid,"bob",{"auction_id":aid,"amount":first,"request_id":rid()})
        self.assertEqual(s,201,b)
        s,b=self.call(land.bid,"carol",{"auction_id":aid,"amount":second,"request_id":rid()})
        self.assertEqual(s,201,b)
        self.assertEqual(self.query("SELECT balance FROM wallets WHERE account=?",
                                    (economy.player_account("bob"),))[0][0],initial_bob)
        self.assertEqual(self.query("SELECT balance FROM wallets WHERE account='system:land_escrow'")[0][0],second)
        closed=self.run_tx(land.close_due,2,now=T0+2*86400)
        self.assertEqual(closed,1)
        self.assertEqual(self.run_tx(land.close_due,2,now=T0+2*86400),0)
        self.assertEqual(self.query("SELECT owner FROM land_parcels WHERE id='1:0'")[0][0],"carol")
        self.assertEqual(self.query("SELECT balance FROM wallets WHERE account='system:land_escrow'")[0][0],0)
        self.assertEqual(self.query("SELECT COUNT(*) FROM ledger_tx WHERE kind='land_auction'")[0][0],1)
        self.check_ledger()

    def test_replayed_bid_no_double_escrow(self):
        s,a=self.start()
        aid=a["auction_id"]
        request=rid()
        payload={"auction_id":aid,"amount":a["start"],"request_id":request}
        first=self.call(land.bid,"bob",payload)
        self.assertEqual(first[0],201,first)
        self.assertEqual(self.call(land.bid,"bob",payload),(200,first[1]))
        self.assertEqual(self.query("SELECT COUNT(*) FROM land_bids WHERE auction_id=?",(aid,))[0][0],1)
        self.assertEqual(self.query("SELECT COUNT(*) FROM ledger_tx WHERE kind='land_bid'")[0][0],1)
        self.check_ledger()

    def test_competing_bids_one_at_a_time(self):
        s,a=self.start()
        aid=a["auction_id"]
        amount=a["start"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            commands=(
                ("bob",{"auction_id":aid,"amount":amount,"request_id":rid()}),
                ("carol",{"auction_id":aid,"amount":amount,"request_id":rid()}))
            responses=list(pool.map(lambda arg:self.call(land.bid,arg[0],arg[1]),commands))
        self.assertEqual(sorted(s for s,_ in responses),[201,409],responses)
        self.assertEqual(self.query("SELECT COUNT(*) FROM land_bids WHERE auction_id=?",(aid,))[0][0],1)
        self.check_ledger()

    def test_cannot_bypass_auction_via_buy_lease_or_second_auction(self):
        s,a=self.start()
        self.assertEqual(s,201,a)
        self.assertEqual(self.buy("bob",1,0)[1]["error"],"auction_or_reservation")
        self.assertEqual(self.call(land.lease,"bob",{"px":1,"py":0,"months":4,"request_id":rid()})[0],409)
        self.assertEqual(self.start()[0],409)
        self.assertEqual(self.call(land.bid,"alice",{"auction_id":a["auction_id"],
                      "amount":a["start"],"request_id":rid()})[0],403)
        self.check_ledger()

    def test_cancel_auction_refunds_escrow_once(self):
        s,a=self.start()
        self.assertEqual(s,201,a)
        s,b=self.call(land.bid,"bob",{"auction_id":a["auction_id"],
                     "amount":a["start"],"request_id":rid()})
        self.assertEqual(s,201,b)
        request={"auction_id":a["auction_id"],"request_id":rid()}
        s,done=self.call(land.cancel_auction,"alice",request)
        self.assertEqual(s,200,done)
        self.assertEqual(self.call(land.cancel_auction,"alice",request),(200,done))
        self.assertEqual(self.query("SELECT balance FROM wallets WHERE account='system:land_escrow'")[0][0],0)
        self.assertEqual(self.query("SELECT COUNT(*) FROM ledger_tx WHERE kind='land_auction_refund'")[0][0],1)
        self.assertEqual(self.query("SELECT status FROM land_parcels WHERE id='1:0'")[0][0],"available")
        self.assertEqual(self.call(land.bid,"carol",{"auction_id":a["auction_id"],
                         "amount":a["start"]+a["min_step"],"request_id":rid()})[0],409)
        self.check_ledger()

    def test_no_bid_closes_without_selling_land(self):
        s,a=self.start()
        self.assertEqual(s,201,a)
        self.assertEqual(self.run_tx(land.close_due,2,now=T0+2*86400),1)
        self.assertEqual(self.query("SELECT owner,status FROM land_parcels WHERE id='1:0'")[0],
                         ("municipal:ufa","available"))
        self.assertEqual(self.query("SELECT winner FROM land_auctions WHERE id=?",
                                    (a["auction_id"],))[0][0],None)
        self.check_ledger()
