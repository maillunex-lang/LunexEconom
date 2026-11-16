"""V2-03 PostgreSQL integration: city growth, chunks, ledger-backed ownership."""
import io
import json
import os
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from server import db
from server.game_server import create_app
from server.ledger.api import reconcile
from server.world import core

DSN=os.getenv('LUNEX_TEST_DATABASE_URL')


def request(app,method,path,body=None,token=None,query='',etag='',ip='10.99.0.1',admin=''):
    raw=json.dumps(body or {}).encode('utf-8')
    result={}
    def start(status,headers):
        result['status']=int(status.split()[0])
        result['headers']=dict(headers)
    env={'REQUEST_METHOD':method,'PATH_INFO':path,'QUERY_STRING':query,
         'CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw),
         'HTTP_AUTHORIZATION':'Bearer '+token if token else '',
         'HTTP_IF_NONE_MATCH':etag,'HTTP_HOST':'localhost:18777',
         'REMOTE_ADDR':ip,'HTTP_X_ADMIN_TOKEN':admin}
    body=b''.join(app(env,start))
    result['body']=json.loads(body) if body else None
    return result


@unittest.skipUnless(DSN,'Set LUNEX_TEST_DATABASE_URL to an isolated PostgreSQL database')
class WorldDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=create_app(DSN)

    @classmethod
    def tearDownClass(cls):
        cls.app.close()

    def user(self):
        username='w'+uuid4().hex[:12]
        ip='10.91.'+str(int(uuid4().hex[:2],16)%240+1)+'.'+str(int(uuid4().hex[:2],16)%240+1)
        data={'consent_personal_data':True,'username':username,'email':username+'@example.com','password':'StrongWorldPass123!'}
        registered=request(type(self).app,'POST','/auth/register',data,ip=ip)
        self.assertEqual(registered['status'],201,registered)
        login=request(type(self).app,'POST','/auth/login',
                      {'username':username,'password':data['password']},ip=ip)
        self.assertEqual(login['status'],200,login)
        return login['body']['access_token'],registered['body']['id']

    def test_cities_and_routes(self):
        payload=request(type(self).app,'GET','/world/cities')
        self.assertEqual(payload['status'],200,payload)
        self.assertEqual(len(payload['body']['cities']),20)
        ufa=request(type(self).app,'GET','/world/cities/ufa')
        self.assertEqual(ufa['body']['level'],1)
        self.assertIn('next_radius',ufa['body'])
        routes=request(type(self).app,'GET','/world/routes',query='from=ufa&to=salavat')
        self.assertEqual(routes['status'],200,routes)
        self.assertGreater(routes['body']['distance_meters'],0)
        self.assertEqual(request(type(self).app,'GET','/world/routes',query='from=ufa&to=phantom')['status'],404)

    def test_chunk_etag_and_events(self):
        first=request(type(self).app,'GET','/world/chunk',query='cx=-3&cy=2')
        self.assertEqual(first['status'],200,first)
        self.assertEqual(len(first['body']['terrain']),12)
        self.assertEqual(first['body']['cell_meters'],20)
        etag=first['headers']['ETag']
        cached=request(type(self).app,'GET','/world/chunk',query='cx=-3&cy=2',etag=etag)
        self.assertEqual(cached['status'],304,cached)
        self.assertEqual(cached['headers']['ETag'],etag)
        self.assertIsNone(cached['body'])
        self.assertEqual(request(type(self).app,'GET','/world/chunk',query='cx=NaN&cy=2')['status'],400)
        events=request(type(self).app,'GET','/world/events',query='after=0')
        self.assertEqual(events['status'],200,events)

    def test_growth_strict_threshold_idempotent_and_receipts(self):
        # Entire test is rolled back. The production ledger and city state are untouched.
        conn=db.connect(DSN)
        try:
            city=core.CITIES['baymak']
            city_id=city['id']
            base=core.growth_stats(conn,city_id)
            self.assertEqual(base['level'],1)
            self.assertEqual(base['total_cells'],625)
            self.assertEqual(base['required_occupied_cells'],376)
            # No production creation here: simulated occupancy cells for the growth engine.
            cells=[(city['x']+dx,city['y']+dy)
                   for dx in range(-12,13) for dy in range(-12,13)]
            with conn.cursor() as cursor:
                for index,(x,y) in enumerate(cells[:375]):
                    cursor.execute(
                        '''INSERT INTO world_occupied_cells(x,y,city_id,building_ref)
                           VALUES(%s,%s,%s,%s)''',
                        (x,y,city_id,'test-building-'+str(index%10))
                    )
            before=core.growth_stats(conn,city_id)
            self.assertEqual(before['occupancy_bp'],6000)
            self.assertFalse(before['ready'])
            self.assertEqual(core.grow_month(conn,40),[])
            x,y=cells[375]
            conn.execute(
                'INSERT INTO world_occupied_cells(x,y,city_id,building_ref) VALUES(%s,%s,%s,%s)',
                (x,y,city_id,'test-building-10')
            )
            self.assertTrue(core.growth_stats(conn,city_id)['ready'])
            unchanged=core.cell_zone(city['x']+10,city['y']+1,core.city_states(conn))
            new_coord=(city['x']+15,city['y']+1)
            cx,cy=new_coord[0]//12,new_coord[1]//12
            old=conn.execute('SELECT version FROM world_chunk_versions WHERE cx=%s AND cy=%s',
                             (cx,cy)).fetchone()
            first=core.grow_month(conn,40)
            self.assertEqual(len(first),1,first)
            self.assertEqual(first[0]['city'],city_id)
            self.assertEqual(core.grow_month(conn,40),[])
            after=core.growth_stats(conn,city_id)
            self.assertEqual(after['level'],2)
            self.assertEqual(after['radius'],15)
            self.assertEqual(after['occupied_cells'],376)
            self.assertEqual(unchanged,core.cell_zone(city['x']+10,city['y']+1,
                                                     core.city_states(conn)))
            now=conn.execute('SELECT version FROM world_chunk_versions WHERE cx=%s AND cy=%s',
                             (cx,cy)).fetchone()[0]
            self.assertGreater(now,old[0] if old else 0)
            self.assertEqual(conn.execute(
                'SELECT count(*) FROM world_growth_receipts WHERE city_id=%s AND month_index=40',
                (city_id,)).fetchone()[0],1)
            event=conn.execute(
                'SELECT payload FROM world_events WHERE version=%s',
                (first[0]['event_version'],)).fetchone()[0]
            self.assertEqual(event['new_radius'],15)
            self.assertEqual(event['reason']['building_count'],11)
            # Monthly handler must also remain idempotent.
            handler=next(fn for _,name,fn in type(self).app.registry.tick_handlers['monthly']
                         if name=='world_growth')
            handler(conn,40)
            self.assertEqual(core.growth_stats(conn,city_id)['level'],2)
            self.assertTrue(reconcile(conn)['ok'])
        finally:
            conn.rollback()
            conn.close()

    def test_land_buy_idempotence_double_sale_and_ledger(self):
        token_a,id_a=self.user()
        token_b,id_b=self.user()
        # City parcel (6..11,6..11), safely within Ufa radius 12.
        px,py=1,1
        req_a='land-'+uuid4().hex
        req_b='land-'+uuid4().hex
        def buy(token,req):
            return request(type(self).app,'POST','/land/buy',
                           {'px':px,'py':py,'request_id':req},token=token)
        with ThreadPoolExecutor(max_workers=2) as pool:
            a,b=list(pool.map(lambda v: buy(*v),[(token_a,req_a),(token_b,req_b)]))
        self.assertEqual(sorted((a['status'],b['status'])),[201,409],(a,b))
        winning_token=token_a if a['status']==201 else token_b
        winning_req=req_a if a['status']==201 else req_b
        repeat=buy(winning_token,winning_req)
        self.assertEqual(repeat['status'],200,repeat)
        self.assertTrue(repeat['body']['idempotent'])
        winner=a if a['status']==201 else b
        self.assertEqual(repeat['body']['transfer_id'],winner['body']['transfer_id'])
        with db.connect(DSN) as conn:
            self.assertEqual(conn.execute(
                'SELECT count(*) FROM world_land_requests WHERE px=%s AND py=%s',
                (px,py)).fetchone()[0],1)
            self.assertTrue(reconcile(conn)['ok'])
        # Distinct request IDs must not resell the same parcel.
        self.assertEqual(buy(winning_token,'other-'+uuid4().hex)['status'],409)

    def test_state_parcel_purchase_and_preservation(self):
        token,buyer=self.user()
        px,py=3,3  # 21..26 from Ufa, free land at level one.
        order=request(type(self).app,'POST','/land/buy',
                      {'px':px,'py':py,'request_id':'land-'+uuid4().hex},token=token)
        self.assertEqual(order['status'],201,order)
        parcel=request(type(self).app,'GET','/land/parcels',query='chunk=1,1')
        self.assertEqual(parcel['status'],200,parcel)
        bought=next(p for p in parcel['body']['parcels'] if p['px']==px and p['py']==py)
        self.assertEqual(bought['owner_kind'],'player')
        self.assertEqual(bought['owner_ref'],str(buyer))
        with db.connect(DSN) as conn:
            self.assertTrue(reconcile(conn)['ok'])

    def test_admin_growth_restricted(self):
        self.assertEqual(request(type(self).app,'GET','/admin/world/growth',query='city=ufa')['status'],403)

    def test_chunk_benchmark_1000_requests(self):
        # Version-only 304 avoids full 144-cell rendering and demonstrates cache.
        first=request(type(self).app,'GET','/world/chunk',query='cx=100&cy=-100')
        self.assertEqual(first['status'],200)
        etag=first['headers']['ETag']
        started=time.monotonic()
        for _ in range(1000):
            got=request(type(self).app,'GET','/world/chunk',query='cx=100&cy=-100',etag=etag)
            self.assertEqual(got['status'],304,got)
        self.assertLess(time.monotonic()-started,120)


if __name__=='__main__':
    unittest.main()
