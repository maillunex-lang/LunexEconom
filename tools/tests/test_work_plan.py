import copy
import unittest
from tools import work_plan as wp


class WorkPlan(unittest.TestCase):
    def setUp(self):
        self.plan = wp.load()

    def test_real_plan_valid(self):
        self.assertEqual(wp.validate(self.plan), [])

    def test_rendered_file_in_sync(self):
        self.assertEqual(wp.OUT.read_text(encoding="utf-8"), wp.render(self.plan))

    def test_ready_only_when_deps_done(self):
        ids = {p["id"] for p in wp.ready(self.plan)}
        for p in self.plan["packages"]:
            if p["status"] == "planned" and not p["depends_on"]:
                self.assertIn(p["id"], ids)
            if p["depends_on"] and p["status"] == "planned":
                done = {x["id"] for x in self.plan["packages"] if x["status"] == "done"}
                self.assertEqual(p["id"] in ids, all(d in done for d in p["depends_on"]))

    def test_one_package_per_lane_per_step(self):
        seen = set()
        for p in self.plan["packages"]:
            key = (p["step"], p["lane"])
            self.assertNotIn(key, seen)
            seen.add(key)

    def test_detects_zone_overlap(self):
        bad = copy.deepcopy(self.plan)
        bad["lanes"]["B"]["zone"].append("server/world/**")
        self.assertTrue(any("пересекаются" in e for e in wp.validate(bad)))

    def test_detects_cycle_or_missing_dep(self):
        bad = copy.deepcopy(self.plan)
        bad["packages"][0]["depends_on"] = ["NOPE"]
        self.assertTrue(wp.validate(bad))

    def test_detects_cross_lane_dependency_in_step(self):
        bad = copy.deepcopy(self.plan)
        for p in bad["packages"]:
            if p["id"] == "B1":
                p["depends_on"] = ["A1"]
        self.assertTrue(any("параллельность" in e for e in wp.validate(bad)))

    def test_prompt_contains_zone_and_criteria(self):
        text = wp.prompt(self.plan, "A1")
        self.assertIn("server/**", text)
        self.assertIn("Критерии готовности", text)
        self.assertIn("ВЫКЛЮЧЕНЫ", text)
        self.assertIn("Godot", wp.prompt(self.plan, "B1"))

    def test_portal_plan_valid_and_prompt_paths(self):
        import json
        plan = json.loads((wp.ROOT / "docs/portal/work_plan.json").read_text(encoding="utf-8"))
        self.assertEqual(wp.validate(plan), [])
        text = wp.prompt(plan, "B1")
        self.assertIn("portal/qa/ui/B1.md", text)
        self.assertIn("portal/static/**", text)
        self.assertNotIn("Godot", text)
        self.assertNotIn("LunexEconom V2", text)
        a = wp.prompt(plan, "A2")
        self.assertIn("portal/qa/server/A2.md", a)
        self.assertIn("portal/hooks/**", a)

    def test_rendered_portal_plan_in_sync(self):
        import json
        plan_path = wp.ROOT / "docs/portal/work_plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        old = (wp.PLAN, wp.OUT)
        try:
            wp.PLAN, wp.OUT = plan_path, plan_path.with_name("WORK_PLAN.md")
            self.assertEqual(wp.OUT.read_text(encoding="utf-8"), wp.render(plan))
        finally:
            wp.PLAN, wp.OUT = old


if __name__ == "__main__":
    unittest.main()
