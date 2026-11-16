"""Worker uses independent DB connection and fake transports."""
import tempfile
import unittest
from pathlib import Path
from portal import db
from portal.backup.worker import tick

class Worker(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=str(Path(self.tmp.name)/"worker.sqlite")
        c=db.connect(self.path,webhook=True,notifications=True)
        c.execute("INSERT INTO projects(slug,name,repo,created) VALUES('demo-project','Demo','',0)")
        c.close()
    def tearDown(self):self.tmp.cleanup()
    def test_tick_without_external_requests(self):
        tick(self.path,{},notifications=True,webhook=True,now=1000000,
             client=lambda *a,**k: (_ for _ in ()).throw(AssertionError("unexpected HTTP")),
             fetch=lambda *a,**k: (_ for _ in ()).throw(AssertionError("unexpected GitHub")))
    def test_overdue_queue_disabled_channels(self):
        c=db.connect(self.path,webhook=True,notifications=True)
        c.execute("INSERT INTO task_state(project_slug,pkg_id,status,submitted_at) VALUES('demo-project','A1','submitted',0)")
        c.close()
        tick(self.path,{},notifications=True,webhook=False,now=1000000)
        c=db.connect(self.path,webhook=True,notifications=True)
        self.assertEqual(c.execute("SELECT count(*) FROM notify_jobs").fetchone()[0],0)
        c.close()
