"""Presence sampling does not write more than once per 30 seconds per player."""
import sqlite3
import unittest
import presence

class PresenceTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        presence.ensure(self.db, "?")
    def tearDown(self): self.db.close()
    def test_touch_throttle_and_versions(self):
        self.assertTrue(presence.touch(self.db,"?","a","1.0","ufa",1000))
        self.assertFalse(presence.touch(self.db,"?","a","1.2","ufa",1001))
        self.assertEqual(presence.players(self.db,"?",1010)[0]["version"],"1.0")
        self.assertTrue(presence.touch(self.db,"?","a","1.2","ufa",1031))
        self.assertTrue(presence.touch(self.db,"?","b","1.0","sterlitamak",1031))
        self.assertEqual(presence.summary(self.db,"?",1031)["online"],2)
        self.assertEqual(presence.summary(self.db,"?",1340)["online"],0)
    def test_peak_and_history(self):
        presence.touch(self.db,"?","a","1","ufa",1200)
        presence.sample(self.db,"?",1200)
        presence.touch(self.db,"?","b","1","ufa",1210)
        presence.sample(self.db,"?",1210)
        self.assertEqual(presence.summary(self.db,"?",1500)["peak_24h"],2)
        self.assertEqual(presence.history(self.db,"?",1500)[0]["online"],2)
    def test_invalid_player_rejected(self):
        self.assertFalse(presence.touch(self.db,"?","","1","",100))
        self.assertEqual(presence.summary(self.db,"?",100)["online"],0)

if __name__=="__main__":unittest.main()
