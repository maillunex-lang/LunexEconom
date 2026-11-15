"""PostgreSQL V2-04: deterministic daily production, stages and ledger."""
import os
import unittest
from uuid import uuid4

from server import db
from server.game_server import create_app
from server.ledger.api import account, reconcile, transfer
from server.world import core as world
from server.enterprises import core as enterprises

DSN=os.getenv('LUNEX_TEST_DATABASE_URL')

@unittest.skipUnless(DSN,'Set LUNEX_TEST_DATABASE_URL to isolated PostgreSQL')
class EnterpriseDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=create_app(DSN)

    @classmethod
    def tearDownClass(cls):
        cls.app.close()

    def test_full_cycle_isolated_transaction(self):
        # Use a fresh test account and one unclaimed parcel. Entire transaction
        # is rolled back, so this test does not mutate other integration fixtures.
        conn=db.connect(DSN)
        try:
            username='enterprise'+uuid4().hex[:12]
            actor_id=conn.execute("""INSERT INTO accounts(username,email,password_hash,role)
              VALUES(%s,%s,'test-hash','player') RETURNING id""",
              (username,username+'@example.test')).fetchone()[0]
            actor={'id':actor_id,'username':username}
            player=account(conn,'player:'+username,'player',actor_id)
            treasury=account(conn,'system:treasury')
            transfer(conn,'enterprise:test-capital:'+username,treasury,player,1000000)
            states=world.city_states(conn)
            found=None
            # Search valid free cells adjacent to generated roads; never rely
            # on a hardcoded location that can change with the world seed.
            for px in range(3,25):
                if found:break
                for py in range(3,25):
                    if conn.execute('SELECT 1 FROM world_parcels WHERE px=%s AND py=%s',(px,py)).fetchone():
                        continue
                    for x in range(px*6,px*6+5):
                        if found:break
                        for y in range(py*6,py*6+5):
                            valid,_=world.placement_valid(conn,'field',x,y)
                            if valid and all(world.cell_zone(a,b,states)[0]=='free'
                                             for a in range(x,x+2) for b in range(y,y+2)):
                                found=(px,py,x,y)
                                break
                    if found:break
            self.assertIsNotNone(found,'No buildable free parcel found')
            px,py,x,y=found
            conn.execute("""INSERT INTO world_parcels(px,py,city_id,owner_kind,owner_ref,paid_amount)
              VALUES(%s,%s,NULL,'player',%s,10000)""",(px,py,str(actor_id)))
            request_id='enterprise-test:'+uuid4().hex
            status,result=enterprises.place(conn,actor,request_id,'field',px,py,x,y)
            self.assertEqual(status,201,result)
            eid=result['id']
            again=enterprises.place(conn,actor,request_id,'field',px,py,x,y)
            self.assertEqual(again[0],200)
            self.assertEqual(again[1]['id'],eid)
            self.assertEqual(conn.execute('SELECT count(*) FROM ledger_transfers WHERE request_id=%s',
              ('enterprise:build:'+request_id,)).fetchone()[0],1)
            # V2-04d: only the first 30% is charged at order time.
            self.assertEqual(conn.execute('SELECT balance FROM ledger_accounts WHERE id=%s',
                                          (player,)).fetchone()[0],988300)
            self.assertEqual(conn.execute('SELECT stage,amount FROM enterprise_stage_payments '
                                          'WHERE enterprise_id=%s',(eid,)).fetchone(),(0,11700))
            start=conn.execute('SELECT started_day FROM enterprises WHERE id=%s',(eid,)).fetchone()[0]
            for day in range(start,start+11):
                enterprises.advance_day(conn,day)
            self.assertEqual(enterprises.stock(conn,eid)['grain']['quantity'],1000)
            self.assertEqual(conn.execute('SELECT COALESCE(sum(amount),0) '
                                          'FROM enterprise_stage_payments WHERE enterprise_id=%s',
                                          (eid,)).fetchone()[0],39000)
            self.assertEqual(conn.execute('SELECT stage FROM enterprises WHERE id=%s',(eid,)).fetchone()[0],4)
            # Reuse the isolated enterprise row to verify the M1 mill recipe.
            conn.execute("UPDATE enterprises SET building_id='mill',recipe_id='mill_flour' WHERE id=%s",(eid,))
            enterprises.adjust(conn,eid,'grain',-900)
            enterprises.production(conn,eid,start+11)
            self.assertEqual(enterprises.stock(conn,eid)['flour']['quantity'],80)
            self.assertEqual(enterprises.stock(conn,eid)['grain']['quantity'],0)
            enterprises.production(conn,eid,start+11)
            self.assertEqual(enterprises.stock(conn,eid)['flour']['quantity'],80)

            self.assertGreaterEqual(conn.execute('SELECT count(*) FROM world_events WHERE payload->>\'enterprise_id\'=%s',(str(eid),)).fetchone()[0],2)
            self.assertTrue(reconcile(conn)['ok'])
        finally:
            conn.rollback()
            conn.close()

    def test_monthly_arrears_isolated_repaid_and_idempotent(self):
        conn=db.connect(DSN)
        try:
            ids=[]
            wallets=[]
            treasury=account(conn,'system:treasury')
            seed=uuid4().hex
            # Create two independent players and enterprises without depending
            # on generated world placement. Roll back the entire fixture.
            for i in range(2):
                username='arrears'+seed[:10]+str(i)
                owner=conn.execute("""INSERT INTO accounts(username,email,password_hash,role)
                  VALUES(%s,%s,'test-hash','player') RETURNING id""",
                  (username,username+'@example.test')).fetchone()[0]
                wallet=account(conn,'player:'+username,'player',owner)
                wallets.append(wallet)
                capital=transfer(conn,'arrears:fixture:'+seed+str(i),treasury,wallet,10000 if i else 1)
                if i==0:
                    transfer(conn,'arrears:empty:'+seed,wallet,treasury,1)
                px=1000000+owner
                py=1000000+owner
                conn.execute("""INSERT INTO world_parcels(px,py,city_id,owner_kind,owner_ref,paid_amount)
                  VALUES(%s,%s,NULL,'player',%s,0)""",(px,py,str(owner)))
                eid=conn.execute("""INSERT INTO enterprises
                  (owner_id,building_id,px,py,x,y,width,height,name,build_cost,
                   build_days,upkeep_month,jobs,storage_capacity,started_day,stage,
                   recipe_id,build_request_id,build_transfer_id)
                  VALUES(%s,'field',%s,%s,%s,%s,1,1,'Arrears test',1,
                         1,100,2,4000,0,4,'field_grain',%s,%s) RETURNING id""",
                  (owner,px,py,px*6,py*6,'arrears:build:'+seed+str(i),capital)).fetchone()[0]
                ids.append(eid)
            broke,solvent=ids
            enterprises.close_month(conn,1)
            self.assertEqual(conn.execute('SELECT balance FROM ledger_accounts WHERE id=%s',(wallets[0],)).fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT balance FROM ledger_accounts WHERE id=%s',(wallets[1],)).fetchone()[0],9700)
            self.assertEqual(conn.execute('SELECT amount,consecutive_months FROM enterprise_arrears WHERE enterprise_id=%s AND paid_at IS NULL',(broke,)).fetchone(),(300,1))
            self.assertEqual(conn.execute('SELECT count(*) FROM enterprise_month_reports WHERE month_index=1 AND enterprise_id=ANY(%s)',(ids,)).fetchone()[0],2)
            enterprises.production(conn,broke,31)
            self.assertEqual(enterprises.stock(conn,broke),{})
            self.assertEqual(conn.execute('SELECT load_bp FROM enterprises WHERE id=%s',(broke,)).fetchone()[0],0)
            enterprises.close_month(conn,2)
            self.assertEqual(conn.execute('SELECT amount,consecutive_months FROM enterprise_arrears WHERE enterprise_id=%s AND month_index=2',(broke,)).fetchone(),(300,2))
            transfer(conn,'arrears:refill:'+seed,treasury,wallets[0],1000)
            enterprises.close_month(conn,3)
            self.assertEqual(conn.execute('SELECT count(*) FROM enterprise_arrears WHERE enterprise_id=%s AND paid_at IS NULL',(broke,)).fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT balance FROM ledger_accounts WHERE id=%s',(wallets[0],)).fetchone()[0],100)
            self.assertEqual(conn.execute('SELECT count(*) FROM ledger_transfers WHERE request_id=%s',(f'enterprise:upkeep:{broke}:3',)).fetchone()[0],1)
            enterprises.production(conn,broke,91)
            self.assertEqual(enterprises.stock(conn,broke)['grain']['quantity'],100)
            enterprises.close_month(conn,3)
            self.assertEqual(conn.execute('SELECT balance FROM ledger_accounts WHERE id=%s',(wallets[0],)).fetchone()[0],100)
            self.assertEqual(conn.execute('SELECT count(*) FROM ledger_transfers WHERE request_id=%s',(f'enterprise:upkeep:{broke}:3',)).fetchone()[0],1)
            self.assertTrue(reconcile(conn)['ok'])
        finally:
            conn.rollback()
            conn.close()

    def test_integer_load_boundaries(self):
        recipe=enterprises.catalog().index['recipes']['mill_flour']
        self.assertEqual(enterprises.load_bp({'grain':{'quantity':50,'quality':50}},recipe,4000,10000),5000)
        self.assertEqual(enterprises.load_bp({'grain':{'quantity':4000,'quality':50}},recipe,4000,10000),10000)
        self.assertEqual(enterprises.load_bp({'grain':{'quantity':100,'quality':50}},recipe,4000,10000),10000)

if __name__=='__main__':
    unittest.main()
