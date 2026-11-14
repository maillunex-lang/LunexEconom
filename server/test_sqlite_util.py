import gc
import os
import sqlite3
import tempfile
import unittest
import uuid
import warnings

import game_server
import sqlite_util


class ClosingConnectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "t.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_with_block_commits_and_closes(self):
        with sqlite_util.open_db(self.path) as db:
            db.execute("CREATE TABLE t(x INTEGER)")
            db.execute("INSERT INTO t VALUES(1)")
        with self.assertRaises(sqlite3.ProgrammingError):      # closed
            db.execute("SELECT 1")
        with sqlite_util.open_db(self.path) as db2:
            self.assertEqual(db2.execute("SELECT x FROM t").fetchall(), [(1,)])

    def test_exception_rolls_back_closes_and_propagates(self):
        with sqlite_util.open_db(self.path) as db:
            db.execute("CREATE TABLE t(x INTEGER)")
        with self.assertRaises(ValueError):
            with sqlite_util.open_db(self.path) as db:
                db.execute("INSERT INTO t VALUES(1)")
                raise ValueError("boom")
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute("SELECT 1")
        with sqlite_util.open_db(self.path) as db2:
            self.assertEqual(db2.execute("SELECT COUNT(*) FROM t").fetchone()[0], 0)


class NoLeakedConnectionsTests(unittest.TestCase):
    def test_server_operations_leave_no_open_connections(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = game_server.DB
            game_server.DB = os.path.join(tmp, "w.sqlite3")
            try:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    status, res = game_server.build("alice", {"kind": "farm", "x": 8, "y": 10, "request_id": str(uuid.uuid4())})
                    game_server.wallet("alice")
                    game_server.market_state()
                    game_server.events(0)
                    game_server.chunk(0, 0)
                    game_server.sell("alice", {"object_id": res["object_id"], "request_id": str(uuid.uuid4())})
                    game_server.loan("alice", {"action": "take", "amount": 10_000, "request_id": str(uuid.uuid4())})
                    game_server.npc_tick()
                    gc.collect()
                leaked = [w for w in caught if issubclass(w.category, ResourceWarning)]
                self.assertEqual(leaked, [], [str(w.message) for w in leaked][:3])
            finally:
                game_server.DB = old


if __name__ == "__main__":
    unittest.main()
