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
            start=conn.execute('SELECT started_day FROM enterprises WHERE id=%s',(eid,)).fetchone()[0]
            for day in range(start,start+11):
                enterprises.advance_day(conn,day)
            self.assertEqual(enterprises.stock(conn,eid)['grain']['quantity'],1000)
            self.assertEqual(conn.execute('SELECT stage FROM enterprises WHERE id=%s',(eid,)).fetchone()[0],4)
            # Reuse the isolated enterprise row to verify the M1 mill recipe.
            conn.execute("UPDATE enterprises SET building_id='mill',recipe_id='mill_flour' WHERE id=%s",(eid,))
            enterprises.adjust(conn,eid,'grain',-900)
            enterprises.production(conn,eid,start+11)
            self.assertEqual(enterprises.stock(conn,eid)['flour']['quantity'],80)
            self.assertEqual(enterprises.stock(conn,eid)['grain']['quantity'],0)
            enterprises.production(conn,eid,start+11)
            self.assertEqual(enterprises.stock(conn,eid)['flour']['quantity'],80)

            self.assertEqual(conn.execute('SELECT count(*) FROM world_events WHERE payload->>\'enterprise_id\'=%s',(str(eid),)).fetchone()[0],2)
            self.assertTrue(reconcile(conn)['ok'])
        finally:
            conn.rollback()
            conn.close()

    def test_integer_load_boundaries(self):
        recipe=enterprises.catalog().index['recipes']['mill_flour']
        self.assertEqual(enterprises.load_bp({'grain':{'quantity':50,'quality':50}},recipe,4000,10000),5000)
        self.assertEqual(enterprises.load_bp({'grain':{'quantity':4000,'quality':50}},recipe,4000,10000),0)
        self.assertEqual(enterprises.load_bp({'grain':{'quantity':100,'quality':50}},recipe,4000,10000),10000)

if __name__=='__main__':
    unittest.main()
