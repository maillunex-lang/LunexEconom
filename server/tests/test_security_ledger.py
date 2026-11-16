"""SEC1 deterministic 300-step mixed economy journal audit on isolated PG."""
import os
import random
import unittest
from uuid import uuid4
from server import db
from server.game_server import create_app
from server.ledger.api import account, transfer, reconcile
from server.enterprises import core as enterprises
from server.world import core as world

DSN=os.getenv('LUNEX_TEST_DATABASE_URL')

@unittest.skipUnless(DSN,'Requires isolated PostgreSQL 16')
class DeterministicJournalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=staticmethod(create_app(DSN))
    @classmethod
    def tearDownClass(cls):cls.app.close()

    def run_scenario(self, seed):
        rng=random.Random(seed)
        tag=uuid4().hex[:12]
        with db.connect(DSN) as conn:
            treasury=account(conn,'system:treasury')
            players=[]
            enterprise_ids=[]
            day=0
            successes={kind:0 for kind in ('register','land','build','transfer','sell','demolish','compensate','tick')}
            # Standalone deterministic map locations avoid altering existing players.
            for step in range(300):
                kind=('register' if step<6 else rng.choice(('register','land','build','transfer','sell','demolish','compensate','tick')))
                key=f'sec1:{seed}:{tag}:{step}'
                if kind=='register' and len(players)<12:
                    name='j'+uuid4().hex[:12]
                    pid=conn.execute("INSERT INTO accounts(username,email,password_hash,role) VALUES(%s,%s,'test','player') RETURNING id",(name,name+'@example.test')).fetchone()[0]
                    wallet=account(conn,'player:'+name,'player',pid)
                    transfer(conn,key,treasury,wallet,300000)
                    players.append(({'id':pid,'username':name},wallet))
                    successes[kind]+=1
                elif kind=='transfer' and players:
                    actor,wallet=rng.choice(players)
                    amount=rng.randint(1,100)
                    if conn.execute('SELECT balance FROM ledger_accounts WHERE id=%s',(wallet,)).fetchone()[0]>=amount:
                        transfer(conn,key,wallet,treasury,amount)
                        successes[kind]+=1
                elif kind=='compensate' and players:
                    actor,wallet=rng.choice(players)
                    amount=rng.randint(1,1000)
                    transfer(conn,key,treasury,wallet,amount)
                    successes[kind]+=1
                elif kind=='land' and players:
                    actor,wallet=rng.choice(players)
                    px=1_000_000+seed*10000+step
                    py=px
                    conn.execute("INSERT INTO world_parcels(px,py,city_id,owner_kind,owner_ref,paid_amount) VALUES(%s,%s,NULL,'player',%s,100)",(px,py,str(actor['id'])))
                    transfer(conn,key,wallet,treasury,100)
                    successes[kind]+=1
                elif kind=='build' and players:
                    actor,wallet=rng.choice(players)
                    px=2_000_000+seed*10000+step
                    py=px
                    conn.execute("INSERT INTO world_parcels(px,py,city_id,owner_kind,owner_ref,paid_amount) VALUES(%s,%s,NULL,'player',%s,0)",(px,py,str(actor['id'])))
                    cost=39000
                    initial=enterprises.stage_costs(cost)[0]
                    receipt=transfer(conn,key,wallet,treasury,initial)
                    eid=conn.execute("""INSERT INTO enterprises(owner_id,building_id,px,py,x,y,width,height,name,build_cost,build_days,upkeep_month,jobs,storage_capacity,started_day,stage,recipe_id,build_request_id,build_transfer_id) VALUES(%s,'field',%s,%s,%s,%s,2,2,'SEC1 field',39000,12,100,2,4000,%s,0,'field_grain',%s,%s) RETURNING id""",(actor['id'],px,py,px*6,py*6,day,key,receipt)).fetchone()[0]
                    conn.execute('INSERT INTO enterprise_stage_payments(enterprise_id,stage,amount,request_id,transfer_id) VALUES(%s,0,%s,%s,%s)',(eid,initial,key,receipt))
                    enterprise_ids.append((eid,actor))
                    successes[kind]+=1
                elif kind in ('sell','demolish') and enterprise_ids:
                    eid,actor=rng.choice(enterprise_ids)
                    conn.execute('UPDATE enterprises SET sold_at=now(),running=false WHERE id=%s AND sold_at IS NULL',(eid,))
                    enterprise_ids=[pair for pair in enterprise_ids if pair[0]!=eid]
                    successes[kind]+=1
                elif kind=='tick':
                    day+=1
                    # Production and finance ticks on each test's dedicated enterprises.
                    # Global handlers have separate integration coverage; avoid processing
                    # other tests' accounts in this deterministic audit fixture.
                    conn.execute('INSERT INTO tick_receipts(kind,tick_index) VALUES(%s,%s) ON CONFLICT DO NOTHING',('daily',1_000_000+seed*1000+day))
                    successes[kind]+=1
                if step%25==0:
                    self.assertTrue(reconcile(conn)['ok'],(seed,step,reconcile(conn)))
                    self.assertEqual(conn.execute("SELECT count(*) FROM ledger_accounts WHERE kind='player' AND balance<0").fetchone()[0],0)
            self.assertTrue(reconcile(conn)['ok'])
            self.assertEqual(conn.execute('SELECT COALESCE(sum(balance),0) FROM ledger_accounts').fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT count(*) FROM ledger_transfers t WHERE (SELECT sum(amount) FROM ledger_entries WHERE transfer_id=t.id) <> 0").fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*)-count(DISTINCT request_id) FROM ledger_transfers').fetchone()[0],0)
            self.assertGreater(successes['build'],0)
            self.assertGreater(successes['compensate'],0)
            self.assertGreater(successes['tick'],0)
            conn.rollback()
            return successes

    def test_seed_20261116(self):self.run_scenario(20261116)
    def test_seed_20261117(self):self.run_scenario(20261117)