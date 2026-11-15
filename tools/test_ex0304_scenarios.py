"""EX-03/EX-04 balance scenarios and old-simulator fingerprint regression."""
import os
import unittest
from unittest import mock

import balance_sim
import ex0304_scenarios

class ExpansionBalanceTests(unittest.TestCase):
    def test_construction_boom_reproducible_and_balanced(self):
        for seed in (20261115,20261116):
            one=ex0304_scenarios.run_scenario("construction_boom",months=24,seed=seed)
            two=ex0304_scenarios.run_scenario("construction_boom",months=24,seed=seed)
            self.assertEqual(one["digest"],two["digest"])
            self.assertEqual(one["invariants"],[])
            self.assertEqual(one["flags"],[])
            self.assertEqual(one["last"]["commissioned"],3)

    def test_land_speculation_reproducible_and_pays_vacant_tax(self):
        for seed in (20261115,20261116):
            one=ex0304_scenarios.run_scenario("land_speculation",months=24,seed=seed)
            two=ex0304_scenarios.run_scenario("land_speculation",months=24,seed=seed)
            self.assertEqual(one["digest"],two["digest"])
            self.assertEqual(one["invariants"],[])
            self.assertEqual(one["flags"],[])
            self.assertGreater(one["last"]["land_tax"],0)

    def test_old_simulator_fingerprint_unchanged_with_features_disabled(self):
        config={"months":6,"seed":2115,"npc_on":False,"strategies":("idle",)}
        with mock.patch.dict(os.environ,{"LAND_ENABLED":"0",
                     "CONSTRUCTION_PROJECTS_ENABLED":"0"}):
            original=balance_sim.run_scenario(**config)
        with mock.patch.dict(os.environ,{},clear=False):
            os.environ.pop("LAND_ENABLED",None)
            os.environ.pop("CONSTRUCTION_PROJECTS_ENABLED",None)
            after=balance_sim.run_scenario(**config)
        self.assertEqual(original["digest"],after["digest"])
        self.assertEqual(original["invariants"],[])
        self.assertEqual(after["invariants"],[])

if __name__=="__main__":
    unittest.main()
