import os
import tempfile
import unittest
from unittest import mock

import clock
import game_server


class ClockMathTests(unittest.TestCase):
    def test_default_is_one_day_per_month(self):
        self.assertEqual(clock.DEFAULT_MONTH_SECONDS, 86400)
        params = (1000, 86400, 0)
        d = clock.describe(params, 1000)
        self.assertEqual((d["year"], d["month"], d["day"], d["month_index"]), (2027, 1, 1, 0))
        d = clock.describe(params, 1000 + 86400)
        self.assertEqual((d["month_index"], d["month"], d["day"]), (1, 2, 1))
        d = clock.describe(params, 1000 + 86400 * 12)
        self.assertEqual((d["year"], d["month"]), (2028, 1))

    def test_day_inside_month(self):
        params = (0, 3000, 0)
        self.assertEqual(clock.describe(params, 1499)["day"], 15)
        self.assertEqual(clock.describe(params, 2999)["day"], 30)
        self.assertEqual(clock.describe(params, 3000)["day"], 1)

    def test_seconds_to_next_month(self):
        d = clock.describe((0, 600, 0), 100)
        self.assertEqual(d["seconds_to_next_month"], 500)

    def test_month_length_has_floor(self):
        with mock.patch.dict(os.environ, {"LUNEX_MONTH_SECONDS": "5"}):
            self.assertEqual(clock.configured_month_seconds(), clock.MIN_MONTH_SECONDS)
        with mock.patch.dict(os.environ, {"LUNEX_MONTH_SECONDS": "abc"}):
            self.assertEqual(clock.configured_month_seconds(), 86400)


class ClockStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = game_server.DB
        game_server.DB = os.path.join(self.tmp.name, "w.sqlite3")

    def tearDown(self):
        game_server.DB = self.old
        self.tmp.cleanup()

    def test_clock_persists_across_calls(self):
        with game_server.connect() as db:
            a = clock.load(db, "?", 5000, 86400)
            b = clock.load(db, "?", 9000, 86400)
        self.assertEqual(a, b)

    def test_rebase_keeps_month_continuous(self):
        with game_server.connect() as db:
            clock.load(db, "?", 0, 86400)
            before = clock.describe(clock.load(db, "?", 86400 * 3 + 100, 86400), 86400 * 3 + 100)
            after_params = clock.load(db, "?", 86400 * 3 + 100, 600)  # switch to fast test months
            after = clock.describe(after_params, 86400 * 3 + 100)
            later = clock.describe(after_params, 86400 * 3 + 100 + 1250)
        self.assertEqual(before["month_index"], 3)
        self.assertEqual(after["month_index"], 3)       # no jump
        self.assertEqual(later["month_index"], 5)       # 1250 s = 2 fast months
        self.assertEqual(after["month_seconds"], 600)

    def test_world_endpoint_state(self):
        state = game_server.clock_state()
        self.assertEqual(state["month_seconds"], 86400)
        self.assertEqual(state["month_index"], 0)
        with mock.patch.dict(os.environ, {"LUNEX_MONTH_SECONDS": "600"}):
            self.assertEqual(game_server.clock_state()["month_seconds"], 600)


if __name__ == "__main__":
    unittest.main()
