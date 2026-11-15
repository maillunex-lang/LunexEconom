"""Isolated SQLite test fixtures for EX-03/EX-04. Never touches live databases."""
import os
import tempfile
import time
import unittest
import uuid
from unittest import mock

import economy
import game_server
import land

T0 = 1_800_000_000

def rid():
    return str(uuid.uuid4())

class SQLiteEXCase(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="lunex-ex0304-")
        self.old_db=game_server.DB
        game_server.DB=os.path.join(self.tmp.name,"world.sqlite3")
        self.flags=mock.patch.dict(os.environ,{"LAND_ENABLED":"1",
                                               "CONSTRUCTION_PROJECTS_ENABLED":"1"})
        self.flags.start()
        self.now=T0
        with game_server.connect():
            pass

    def tearDown(self):
        self.flags.stop()
        game_server.DB=self.old_db
        self.tmp.cleanup()

    def call(self,fn,owner,payload,now=None):
        with game_server.LOCK,game_server.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            land.migrate_existing(db,"?")
            return fn(db,"?",owner,payload,self.now if now is None else now)

    def run_tx(self,fn,*args,now=None):
        with game_server.LOCK,game_server.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return fn(db,"?",*args,self.now if now is None else now)

    def fund(self,owner,extra=12_000_000):
        with game_server.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            economy.ensure_wallet(db,"?",owner,self.now)
            if extra:
                economy.post(db,"?","test_grant","isolated test-only funds",
                             [(economy.player_account(owner),extra),(economy.TREASURY,-extra)],self.now)

    def query(self,query,args=()):
        with game_server.connect() as db:
            return db.execute(query,args).fetchall()

    def buy(self,owner="alice",px=0,py=0,r=None):
        return self.call(land.buy,owner,{"px":px,"py":py,"request_id":r or rid()})

    def check_ledger(self):
        self.assertEqual(self.query("""SELECT tx_id FROM ledger_entries
                GROUP BY tx_id HAVING SUM(amount)<>0"""),[])
        self.assertEqual(self.query("SELECT COALESCE(SUM(balance),0) FROM wallets")[0][0],0)
        self.assertEqual(self.query("""SELECT account,balance FROM wallets
                       WHERE account LIKE 'player:%' AND balance<0"""),[])
