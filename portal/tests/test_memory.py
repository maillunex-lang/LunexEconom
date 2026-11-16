import json
import tempfile
import unittest
from pathlib import Path

from portal.memory import context, decisions, repomap, search
from portal.memory.redact import MASK, has_secret, redact

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "ghp_" + "a1B2c3D4" * 5


class RedactTests(unittest.TestCase):
    def test_masks_secrets_keeps_text(self):
        out = redact("токен %s для входа" % TOKEN)
        self.assertNotIn(TOKEN, out)
        self.assertIn(MASK, out)
        self.assertIn("для входа", out)

    def test_multiple_lines_and_other_kinds(self):
        text = "a\nkey AKIA" + "ABCDEFGHIJKLMNOP\nb\n-----BEGIN PRIVATE KEY-----"
        out = redact(text)
        self.assertEqual(out.count(MASK), 2)
        self.assertEqual(out.splitlines()[0], "a")

    def test_safe_values_and_empty(self):
        self.assertEqual(redact("password = 'correct-horse-battery'"), "password = 'correct-horse-battery'")
        self.assertEqual(redact(""), "")
        self.assertEqual(redact(None), "")
        self.assertFalse(has_secret("обычный текст"))
        self.assertTrue(has_secret(TOKEN))


class RepoMapTests(unittest.TestCase):
    def make(self):
        d = Path(tempfile.mkdtemp())
        (d / "app").mkdir()
        (d / "app" / "core.py").write_text('"""Ядро приложения."""\nx=1\n', encoding="utf-8")
        (d / "app" / "util.py").write_text("# Вспомогательные функции\n", encoding="utf-8")
        (d / "docs").mkdir()
        (d / "docs" / "guide.md").write_text("\n# Руководство\nтекст", encoding="utf-8")
        (d / "docs" / "shot.png").write_bytes(b"\x89PNG")
        (d / ".git").mkdir()
        (d / ".git" / "config").write_text("x", encoding="utf-8")
        (d / "run.sh").write_text("#!/bin/sh\n# Запуск проекта\n", encoding="utf-8")
        return d

    def test_scan_skips_binary_and_service_dirs_and_describes(self):
        items = {i["path"]: i for i in repomap.scan(self.make())}
        self.assertNotIn("docs/shot.png", items)
        self.assertFalse(any(p.startswith(".git/") for p in items))
        self.assertEqual(items["app/core.py"]["about"], "Ядро приложения.")
        self.assertEqual(items["app/util.py"]["about"], "Вспомогательные функции")
        self.assertEqual(items["docs/guide.md"]["about"], "Руководство")
        self.assertEqual(items["run.sh"]["about"], "Запуск проекта")

    def test_render_groups_and_budget(self):
        items = repomap.scan(self.make())
        text = repomap.render(items)
        self.assertIn("app/ (2 файлов)", text)
        self.assertIn("app/core.py: Ядро приложения.", text)
        self.assertLessEqual(len(repomap.render(items, max_chars=40)), 120)

    def test_max_files(self):
        self.assertEqual(len(repomap.scan(self.make(), max_files=2)), 2)

    def test_real_repo_has_portal_map(self):
        text = repomap.render(repomap.scan(ROOT / "portal"), max_chars=3000)
        self.assertIn("tests/", text)


DOCS = [
    {"id": "d1", "kind": "doc", "title": "Уведомления MAX и Telegram", "text": "Адаптеры каналов, привязка по коду, антишум.", "url": "/docs/05"},
    {"id": "d2", "kind": "decision", "title": "Автоприёмка", "text": "Задача закрывается сама после слияния PR и зелёного CI.", "url": ""},
    {"id": "d3", "kind": "report", "title": "Отчёт A4", "text": "Реализованы уведомления, очередь, повторы до трёх раз.", "url": ""},
    {"id": "d4", "kind": "lesson", "title": "Ловушка", "text": "Не перенаправлять вывод render в файл.", "url": ""},
]


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.index = search.build(DOCS)

    def test_finds_by_word_forms(self):
        r = search.search(self.index, "уведомление каналы")
        self.assertEqual(r[0]["id"], "d1")
        self.assertIn("d3", [x["id"] for x in r])

    def test_title_weighs_more_and_kinds_filter(self):
        self.assertEqual(search.search(self.index, "автоприемка")[0]["id"], "d2")
        r = search.search(self.index, "уведомления", kinds=["report"])
        self.assertEqual([x["id"] for x in r], ["d3"])

    def test_yo_and_case(self):
        self.assertTrue(search.search(self.index, "ПЕРЕНАПРАВЛЯТЬ вывод"))

    def test_no_match_and_empty(self):
        self.assertEqual(search.search(self.index, "квантовый"), [])
        self.assertEqual(search.search(self.index, ""), [])
        self.assertEqual(search.search(search.build([]), "что угодно"), [])

    def test_snippet_and_limit(self):
        r = search.search(self.index, "уведомления", limit=1)
        self.assertEqual(len(r), 1)
        self.assertTrue(r[0]["snippet"])


class DecisionTests(unittest.TestCase):
    MD = ("# Решения\n\n## Принято (по обсуждению)\n- **Автоприёмка (2026-11-16):** задача закрывается сама. Подробности ниже.\n- Вебхуки нужны.\n\n"
          "## Вопросы с рекомендацией\n- Не должно попасть\n")

    def test_parse_only_accepted_section(self):
        d = decisions.parse_markdown(self.MD)
        self.assertEqual(len(d), 2)
        self.assertEqual(d[0]["date"], "2026-11-16")
        self.assertTrue(d[0]["title"].startswith("Автоприёмка"))
        self.assertEqual(d[1]["id"], "D2")

    def test_parse_real_file(self):
        d = decisions.parse_markdown((ROOT / "docs" / "portal" / "DECISIONS.md").read_text(encoding="utf-8"))
        self.assertGreater(len(d), 5)
        self.assertTrue(all(x["text"] for x in d))

    def test_add_dedupe_validation_and_redaction(self):
        l, e = decisions.add([], "Выбираем MAX", "Первым каналом будет MAX", date="2026-11-17")
        self.assertEqual((e["id"], e["date"]), ("D1", "2026-11-17"))
        l2, e2 = decisions.add(l, "выбираем max", "Первым каналом будет MAX")
        self.assertIsNone(e2)
        with self.assertRaises(ValueError):
            decisions.add(l, "ab", "x")
        with self.assertRaises(ValueError):
            decisions.add(l, "Длинное", "x" * 800)
        _, s = decisions.add(l, "Токен", "используем " + TOKEN)
        self.assertNotIn(TOKEN, s["text"])


PLAN = {"packages": [
    {"id": "A1", "title": "Один", "short": "Один", "lane": "A", "depends_on": [], "status": "done"},
    {"id": "A2", "title": "Два", "short": "Два", "lane": "A", "depends_on": ["A1"], "status": "planned"},
    {"id": "B1", "title": "Три", "short": "Три", "lane": "B", "depends_on": [], "status": "planned"},
    {"id": "B2", "title": "Четыре", "short": "Четыре", "lane": "B", "depends_on": ["B1"], "status": "planned"}]}
PROJECT = {"name": "Демо", "repo": "o/demo", "branch": "main", "description": "Описание проекта"}


class ContextTests(unittest.TestCase):
    def test_sections_and_next_actions(self):
        states = {"B1": {"status": "submitted"}}
        t = context.build(PROJECT, PLAN, states, decisions=[{"date": "2026-11-16", "title": "Решение", "text": "Текст"}],
                          lessons=[{"text": "Не делать X"}], open_prs=[{"number": 5, "title": "PR", "ci": "зелёный"}], events=["событие"])
        for s in ("Контекст проекта «Демо»", "Принять или вернуть B1", "Можно выдавать A2", "Ловушки", "Решения владельца", "Открытые PR", "Последние события"):
            self.assertIn(s, t)
        self.assertNotIn("Можно выдавать B2", t)
        self.assertIn("принято: 1", t)

    def test_done_in_plan_counts_without_states(self):
        t = context.build(PROJECT, PLAN, {})
        self.assertNotIn("- A1 «Один»", t)
        self.assertIn("Можно выдавать A2", t)

    def test_budget_is_respected(self):
        big = [{"text": "правило " * 40} for _ in range(30)]
        t = context.build(PROJECT, PLAN, {}, lessons=big, decisions=[{"title": "T", "text": "x" * 600}] * 20, max_chars=900)
        self.assertLessEqual(len(t), 900)
        self.assertIn("Что делать сейчас", t)

    def test_secrets_never_leak(self):
        t = context.build({"name": "Демо", "description": "ключ " + TOKEN}, PLAN, {}, lessons=[{"text": "токен " + TOKEN}],
                          decisions=[{"title": "d", "text": TOKEN}], events=[TOKEN])
        self.assertNotIn(TOKEN, t)
        self.assertIn(MASK, t)

    def test_repo_map_included_and_empty_inputs(self):
        items = [{"path": "app/core.py", "size": 1, "about": "Ядро"}]
        self.assertIn("Карта репозитория", context.build(PROJECT, PLAN, {}, items=items))
        t = context.build({"name": "Пусто"}, None, None)
        self.assertIn("Контекст проекта «Пусто»", t)

    def test_real_portal_plan(self):
        plan = json.loads((ROOT / "docs" / "portal" / "work_plan.json").read_text(encoding="utf-8"))
        t = context.build({"name": "CreatePortal", "repo": "maillunex-lang/LunexEconom"}, plan, {}, items=repomap.scan(ROOT / "portal"))
        self.assertLessEqual(len(t), 6000)
        self.assertIn("План и статусы", t)

    def test_roles(self):
        self.assertIn("исполнитель", context.build(PROJECT, PLAN, {}, role="executor"))


if __name__ == "__main__":
    unittest.main()
