import os
import tempfile
import unittest
import uuid
from unittest.mock import patch
import game_server
import construction_stages

class ConstructionStageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old=game_server.DB
        game_server.DB=os.path.join(self.tmp.name,'world.sqlite3')
        self.env=patch.dict(os.environ,{'LUNEX_CONSTRUCTION_STEP_SECONDS':'10'})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        game_server.DB=self.old
        self.tmp.cleanup()

    def test_auto_progression_and_idempotent_events(self):
        status,result=game_server.build('tester',{'kind':'factory','x':8,'y':10,'request_id':str(uuid.uuid4())})
        self.assertEqual(status,201,result)
        oid=result['object_id']
        self.assertEqual(next(e for e in result['events'] if e['kind']=='building_created')['construction_stage'],'foundation')
        with game_server.connect() as db:
            next_at=db.execute('SELECT next_at FROM construction_stages WHERE object_id=?',(oid,)).fetchone()[0]
            self.assertEqual(construction_stages.advance(db,'?',next_at-1),0)
            self.assertGreater(construction_stages.advance(db,'?',next_at),0)
            self.assertEqual(db.execute('SELECT stage FROM construction_stages WHERE object_id=?',(oid,)).fetchone()[0],'frame')
            count=db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
            self.assertEqual(construction_stages.advance(db,'?',next_at),0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],count)
            self.assertGreater(construction_stages.advance(db,'?',next_at+10),0)
            self.assertEqual(db.execute('SELECT stage FROM construction_stages WHERE object_id=?',(oid,)).fetchone()[0],'complete')
            self.assertEqual(construction_stages.advance(db,'?',next_at+100),0)
            db.commit()
        stage_events=[e for e in game_server.events(0)[1]['events'] if e['kind']=='building_created' and e['object_id']==oid]
        self.assertEqual([e['construction_stage'] for e in stage_events],['foundation','frame','complete'])
        snapshot=game_server.chunk(0,0)[1]['cells']
        self.assertTrue(any(c.get('object_id')==oid and c.get('construction_stage')=='complete' for c in snapshot))

    def test_restart_persists_stage(self):
        status,result=game_server.build('tester',{'kind':'factory','x':8,'y':10,'request_id':str(uuid.uuid4())})
        self.assertEqual(status,201)
        with game_server.connect() as db:
            self.assertEqual(db.execute('SELECT stage FROM construction_stages WHERE object_id=?',(result['object_id'],)).fetchone()[0],'foundation')