"""SEC1 concurrent HTTP and ledger invariants, isolated PostgreSQL only."""
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from server import db
from server.game_server import create_app
from server.ledger.api import account, transfer, reconcile
from server.tests.test_platform_v201 import request
from server.world import core as world

DSN = os.getenv('LUNEX_TEST_DATABASE_URL')

@unittest.skipUnless(DSN, 'Requires isolated PostgreSQL 16')
class ConcurrentSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = staticmethod(create_app(DSN))

    @classmethod
    def tearDownClass(cls):
        cls.app.close()

    def player(self):
        name = 'c'+uuid4().hex[:13]
        password = 'StrongConcurrentPass123!'
        credentials = {'consent_personal_data':True,'username':name,'email':name+'@example.test','password':password}
        code, created = request(self.app, 'POST', '/auth/register', credentials, ip='10.140.'+str(int(name[1:3],16)%240+1)+'.'+str(int(name[3:5],16)%240+1))
        self.assertEqual(code,201,created)
        code, auth = request(self.app, 'POST', '/auth/login', {'username':name,'password':password},ip='10.141.'+str(int(name[5:7],16)%240+1)+'.'+str(int(name[7:9],16)%240+1))
        self.assertEqual(code,200,auth)
        return {'id':created['id'],'name':name,'token':auth['access_token']}

    def run_concurrent(self, count, worker):
        barrier = threading.Barrier(count)
        def task(i):
            barrier.wait(timeout=30)
            return worker(i)
        with ThreadPoolExecutor(max_workers=count) as pool:
            return list(pool.map(task,range(count),timeout=60))

    def site(self):
        with db.connect(DSN) as conn:
            states=world.city_states(conn)
            for px in range(3,25):
                for py in range(3,25):
                    if conn.execute('SELECT 1 FROM world_parcels WHERE px=%s AND py=%s',(px,py)).fetchone():
                        continue
                    for x in range(px*6,px*6+5):
                        for y in range(py*6,py*6+5):
                            ok,_=world.placement_valid(conn,'field',x,y)
                            if ok and all(world.cell_zone(a,b,states)[0]=='free' for a in range(x,x+2) for b in range(y,y+2)):
                                return px,py,x,y
        self.fail('No suitable site')

    def test_twenty_idempotent_builds_one_charge(self):
        actor=self.player()
        px,py,x,y=self.site()
        with db.connect(DSN) as conn:
            conn.execute("INSERT INTO world_parcels(px,py,city_id,owner_kind,owner_ref,paid_amount) VALUES(%s,%s,NULL,'player',%s,10000)",(px,py,str(actor['id'])))
        req='cbuild:'+uuid4().hex
        payload={'request_id':req,'building_id':'field','px':px,'py':py,'x':x,'y':y}
        results=self.run_concurrent(20,lambda i: request(self.app,'POST','/enterprises',payload,token=actor['token']))
        self.assertEqual([status for status,_ in results].count(201),1,results)
        self.assertEqual([status for status,_ in results].count(200),19,results)
        with db.connect(DSN) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM enterprises WHERE build_request_id=%s',(req,)).fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT count(*) FROM ledger_transfers WHERE request_id=%s',('enterprise:build:'+req,)).fetchone()[0],1)
            self.assertTrue(reconcile(conn)['ok'])

    def test_two_land_buyers_one_winner(self):
        first,second=self.player(),self.player()
        with db.connect(DSN) as conn:
            states=world.city_states(conn)
            site=next((px,py) for px in range(40,110) for py in range(40,110)
                      if world.land_context(px*6+3,py*6+3,states)[1]=='state'
                      and conn.execute('SELECT 1 FROM world_parcels WHERE px=%s AND py=%s',(px,py)).fetchone() is None)
        px,py=site
        results=self.run_concurrent(2,lambda i: request(self.app,'POST','/land/buy',{'px':px,'py':py,'request_id':'cbuy:'+uuid4().hex},token=(first,second)[i]['token']))
        self.assertEqual(sorted(code for code,_ in results),[201,409],results)
        with db.connect(DSN) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM world_land_requests WHERE px=%s AND py=%s',(px,py)).fetchone()[0],1)
            self.assertTrue(reconcile(conn)['ok'])

    def test_twenty_players_compete_for_same_cells(self):
        # A parcel can have one owner: emulate competing authenticated writes
        # against the same footprint to check the occupancy unique constraint.
        owner=self.player()
        px,py,x,y=self.site()
        with db.connect(DSN) as conn:
            conn.execute("INSERT INTO world_parcels(px,py,city_id,owner_kind,owner_ref,paid_amount) VALUES(%s,%s,NULL,'player',%s,10000)",(px,py,str(owner['id'])))
        # Other actors must fail on ownership; all attempts share target cells.
        actors=[owner]+[self.player() for _ in range(19)]
        results=self.run_concurrent(20,lambda i: request(self.app,'POST','/enterprises',
          {'request_id':'race:'+uuid4().hex,'building_id':'field','px':px,'py':py,'x':x,'y':y},
          token=actors[i]['token']))
        self.assertEqual([code for code,_ in results].count(201),1,results)
        self.assertEqual([code for code,_ in results].count(409),19,results)
        with db.connect(DSN) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM world_occupied_cells WHERE x=%s AND y=%s',(x,y)).fetchone()[0],1)
            self.assertTrue(reconcile(conn)['ok'])

    def test_supply_and_cells_parallel_owner_only(self):
        owner=self.player()
        px,py,x,y=self.site()
        with db.connect(DSN) as conn:
            conn.execute("INSERT INTO world_parcels(px,py,city_id,owner_kind,owner_ref,paid_amount) VALUES(%s,%s,NULL,'player',%s,10000)",(px,py,str(owner['id'])))
        code,building=request(self.app,'POST','/enterprises',
            {'request_id':'settings:'+uuid4().hex,'building_id':'field','px':px,'py':py,'x':x,'y':y},token=owner['token'])
        self.assertEqual(code,201,building)
        eid=building['id']
        # A field is not a store; concurrent calls must remain safe and not
        # silently create retail cells, while supply accepts empty inputs.
        results=self.run_concurrent(2,lambda i: request(self.app,'PUT',
            f'/enterprises/{eid}/'+('supply' if i==0 else 'cells'),
            {'inputs':{}} if i==0 else {'cells':[]},token=owner['token']))
        self.assertEqual(results[0][0],200,results)
        self.assertEqual(results[1][0],409,results)
        with db.connect(DSN) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM retail_cells WHERE enterprise_id=%s',(eid,)).fetchone()[0],0)
            self.assertTrue(reconcile(conn)['ok'])

    def test_fifty_opposing_wallet_transfers(self):
        name='wallet'+uuid4().hex[:10]
        with db.connect(DSN) as conn:
            a=account(conn,'player:'+name+'a','player')
            b=account(conn,'player:'+name+'b','player')
            t=account(conn,'system:treasury')
            transfer(conn,'security:fund:'+name+'a',t,a,10000)
            transfer(conn,'security:fund:'+name+'b',t,b,10000)
        results=self.run_concurrent(50,lambda i: self._transfer(name,i,a,b))
        self.assertEqual(results,[True]*50)
        with db.connect(DSN) as conn:
            amounts=conn.execute('SELECT balance FROM ledger_accounts WHERE id=ANY(%s) ORDER BY id',([a,b],)).fetchall()
            self.assertEqual(sum(row[0] for row in amounts),20000)
            self.assertGreaterEqual(min(row[0] for row in amounts),0)
            self.assertTrue(reconcile(conn)['ok'])

    def _transfer(self,name,i,a,b):
        with db.connect(DSN) as conn:
            transfer(conn,'security:transfer:'+name+':'+str(i),a if i%2 else b,b if i%2 else a,1)
        return True

    def test_twenty_concurrent_compensations_same_key(self):
        player=self.player()
        key='seccomp:'+uuid4().hex
        secret='SEC1_TEST_EMERGENCY_ADMIN_TOKEN_1234567'
        from unittest.mock import patch
        with patch.dict(os.environ,{'LUNEX_ADMIN_TOKEN':secret}):
            results=self.run_concurrent(20,lambda i: request(self.app,'POST',f'/admin/players/{player["id"]}/compensate',{'amount':20,'reason':'security test','ticket':'SEC1','request_id':key},admin_token=secret))
        self.assertEqual([code for code,_ in results],[200]*20,results)
        self.assertEqual(len({body['transfer_id'] for _,body in results}),1)
        with db.connect(DSN) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM ledger_transfers WHERE request_id=%s',(key,)).fetchone()[0],1)
            self.assertTrue(reconcile(conn)['ok'])
