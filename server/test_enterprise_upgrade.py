import tempfile
import unittest
import os
import sqlite3
import economy
import enterprise_upgrade

class EquipmentUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = sqlite3.connect(os.path.join(self.tmp.name, "test.sqlite"))
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("CREATE TABLE buildings(id TEXT PRIMARY KEY, owner TEXT, kind TEXT, x INTEGER, y INTEGER, created INTEGER)")
        self.db.execute("CREATE TABLE building_dimensions(object_id TEXT PRIMARY KEY REFERENCES buildings(id),width INTEGER,height INTEGER,equipment_level INTEGER DEFAULT 1)")
        for stmt in economy.SCHEMA:
            self.db.execute(stmt)
        self.db.execute("INSERT INTO buildings VALUES('b1','alice','factory',1,2,0)")
        economy.ensure_wallet(self.db, "?", "alice", 100)
    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()
    def test_upgrade_preserves_building_and_balanced_ledger(self):
        initial = economy.balance(self.db, "?", "alice")
        status, result = enterprise_upgrade.upgrade_equipment(self.db, "?", "alice", "b1", 2, 200)
        self.assertEqual(status, 201)
        self.assertEqual(economy.balance(self.db, "?", "alice"), initial - result["cost"])
        self.assertEqual(self.db.execute("SELECT owner,kind FROM buildings WHERE id='b1'").fetchone(), ("alice","factory"))
        self.assertEqual(self.db.execute("SELECT width,height,equipment_level FROM building_dimensions").fetchone(), (3,2,2))
        self.assertEqual(self.db.execute("SELECT SUM(amount) FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0").fetchall(), [])
        self.assertEqual(enterprise_upgrade.upgrade_equipment(self.db, "?", "alice", "b1", 2, 201)[0], 409)
        self.assertEqual(enterprise_upgrade.upgrade_equipment(self.db, "?", "alice", "b1", 3, 202)[0], 201)
    def test_rejects_foreign_owner_and_missing_building(self):
        self.assertEqual(enterprise_upgrade.upgrade_equipment(self.db, "?", "bob", "b1", 2, 100)[0], 403)
        self.assertEqual(enterprise_upgrade.upgrade_equipment(self.db, "?", "alice", "missing", 2, 100)[0], 404)
    def test_insufficient_funds_no_changes(self):
        self.db.execute("UPDATE wallets SET balance=0 WHERE account=?", (economy.player_account("alice"),))
        self.assertEqual(enterprise_upgrade.upgrade_equipment(self.db, "?", "alice", "b1", 2, 100)[0], 402)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM building_dimensions").fetchone()[0], 0)

if __name__ == "__main__":
    unittest.main()