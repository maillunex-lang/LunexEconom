"""Мастер «Создать проект»: промпт для ИИ-директора и скелет репозитория."""
from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

TPL = Path(__file__).with_name("templates")
SLUG = re.compile(r"^[a-z][a-z0-9-]{1,38}[a-z0-9]$")

AI_RULES = """# Правила работы ИИ в проекте {name}

1. Проектом руководит ИИ-директор: проектирует, пишет задания, принимает работу и сливает в `main`. Исполнители (другие ИИ) работают в своих ветках по заданиям из `docs/WORK_PLAN.md` и не меняют общие файлы директора (список в `docs/work_plan.json`, `rules.shared_files_director_only`).
2. Секреты (пароли, токены, ключи) не пишутся в репозиторий и в чат. Если нужен секрет, владелец кладёт его на сервер напрямую.
3. Любые действия над серверами владельца, ключами, деньгами, удаление данных и публикация релизов выполняются только по прямой команде владельца.
4. Деньги и расчёты (если есть) только целыми числами; все числа баланса помечаются `balance: draft` до утверждения.
5. Каждая задача принимается по проверкам: тесты, зона файлов, пробное слияние с `main`, CI. Работа без проверок не принимается.
6. Слияние в `main` выполняет только директор. Исполнитель открывает pull request и не сливает его.
7. Задачи ведутся в `docs/work_plan.json` по протоколу `docs/PORTAL_PROTOCOL.md`; портал показывает их владельцу.
"""

README = """# {name}

{description}

Репозиторий: {repo}

## Как здесь работают
- Проектирование и решения: `docs/gdd/`, решения владельца в `docs/gdd/DECISIONS_APPROVED.md`.
- План работ и задания исполнителям: `docs/WORK_PLAN.md` (источник `docs/work_plan.json`), команды `python tools/work_plan.py next|prompt <id>|set <id> done|check|render`.
- Правила для ИИ: `docs/AI_RULES.md`, протокол портала: `docs/PORTAL_PROTOCOL.md`, передача дел: `docs/DIRECTOR_HANDOVER.md`.
"""

HANDOVER = """# Передача дел директору проекта {name}

Порядок чтения: README.md, docs/AI_RULES.md, docs/PORTAL_PROTOCOL.md, docs/WORK_PLAN.md, docs/gdd/DECISIONS_APPROVED.md.
Работа: `python tools/work_plan.py next` показывает, что выдавать; `prompt <id>` печатает задание; после приёмки и слияния `set <id> done`.
Приёмка: пробное слияние с main, тесты проекта, проверка зоны файлов (`git diff --name-only`), CI, затем слияние squash.
Чего не делать: менять общие файлы без решения владельца; хранить секреты; действовать на серверах без команды владельца.
"""

STARTER_PLAN = {
    "updated": "2026-01-01",
    "rules": {"shared_files_director_only": ["README.md", "docs/PROGRESS.md", "docs/work_plan.json", "docs/WORK_PLAN.md", "docs/gdd/**", "docs/AI_RULES.md", "docs/PORTAL_PROTOCOL.md"],
              "branch_pattern": "v1/<id>-<slug>", "merge": "только директор после проверки"},
    "lanes": {
        "A": {"name": "Ядро", "who": "Исполнитель №1", "zone": ["src/core/**", "tests/core/**"], "note": "Только ядро проекта и его тесты.", "checks": ["Перед сдачей прогони тесты ядра и приложи результат."]},
        "B": {"name": "Интерфейс", "who": "Исполнитель №2", "zone": ["src/ui/**", "tests/ui/**"], "note": "Только интерфейс; работает по контракту через заглушки.", "checks": ["Перед сдачей прогони тесты интерфейса и приложи результат."]},
    },
    "packages": [
        {"id": "A1", "title": "Каркас ядра", "lane": "A", "step": 1, "depends_on": [], "gdd": ["01"], "goal": "Создать каркас ядра проекта по документу docs/gdd/01.", "done_when": ["тесты ядра проходят", "зона файлов соблюдена"], "zone_extra": [], "status": "planned", "size": "M"},
        {"id": "B1", "title": "Каркас интерфейса", "lane": "B", "step": 1, "depends_on": [], "gdd": ["01"], "goal": "Создать каркас интерфейса по документу docs/gdd/01 на заглушках.", "done_when": ["тесты интерфейса проходят", "зона файлов соблюдена"], "zone_extra": [], "status": "planned", "size": "M"},
    ],
}

CI = """name: Checks
on: [push, pull_request]
jobs:
  plan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python3 tools/work_plan.py check
"""


def files_for(name, repo, description):
    plan = json.dumps(STARTER_PLAN, ensure_ascii=False, indent=1) + "\n"
    out = {
        "README.md": README.format(name=name, repo=repo or "(укажите)", description=description or "Описание проекта."),
        "docs/AI_RULES.md": AI_RULES.format(name=name),
        "docs/PORTAL_PROTOCOL.md": (TPL / "PORTAL_PROTOCOL.md").read_text(encoding="utf-8"),
        "docs/DIRECTOR_HANDOVER.md": HANDOVER.format(name=name),
        "docs/work_plan.json": plan,
        "docs/gdd/DECISIONS_APPROVED.md": f"# Утверждённые решения владельца ({name})\n\n(пока пусто)\n",
        "docs/gdd/01_OVERVIEW.md": f"# 01. Обзор проекта {name}\n\n(директор заполняет: цель, пользователи, основные модули, критерии приёмки)\n",
        "docs/PROGRESS.md": f"# {name}: журнал приёмки\n",
        "tools/work_plan.py": (TPL / "work_plan.py").read_text(encoding="utf-8"),
        "tools/__init__.py": "",
        ".github/workflows/checks.yml": CI,
    }
    return out


def render_plan_md(files):
    """WORK_PLAN.md собирается тем же инструментом, что поставляется с проектом."""
    import importlib.util
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "docs").mkdir()
        (root / "tools").mkdir()
        (root / "tools" / "work_plan.py").write_text(files["tools/work_plan.py"], encoding="utf-8")
        (root / "docs" / "work_plan.json").write_text(files["docs/work_plan.json"], encoding="utf-8")
        spec = importlib.util.spec_from_file_location("wp_boot", root / "tools" / "work_plan.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.render(mod.load())


def director_prompt(name, repo, description):
    return f"""Ты ИИ-директор нового проекта «{name}». Репозиторий: {repo or '(будет создан владельцем)'}. Описание: {description or '(уточни у владельца)'}.

Твоя роль: проектируешь, ставишь задачи исполнителям (другим ИИ), принимаешь их работу и сливаешь в main. Исполнители работают в отдельных ветках и в main не сливают.

1. Организуй репозиторий: распакуй в корень скелет проекта из портала (кнопка «Скачать скелет репозитория»: README, docs/AI_RULES.md, docs/PORTAL_PROTOCOL.md, docs/work_plan.json, tools/work_plan.py, CI). Прочитай docs/AI_RULES.md, docs/PORTAL_PROTOCOL.md и docs/DIRECTOR_HANDOVER.md полностью.
2. Спроектируй проект вместе с владельцем: обзор в docs/gdd/01_OVERVIEW.md, решения владельца записывай в docs/gdd/DECISIONS_APPROVED.md. Не придумывай решения за владельца: предлагай рекомендацию и фиксируй его ответ.
3. Разбей работу на этапы и пакеты по протоколу docs/PORTAL_PROTOCOL.md: две независимые линии исполнителей (A и B) с непересекающимися зонами файлов, шаги по порядку, критерии готовности у каждого пакета. Проверяй: `python tools/work_plan.py check`, затем `python tools/work_plan.py render`.
4. Задания исполнителям не пиши руками: `python tools/work_plan.py prompt <id>`. Владелец берёт готовый промпт на портале.
5. Принимай работу: пробное слияние с main, тесты проекта, проверка зоны файлов, CI. После слияния `python tools/work_plan.py set <id> done`.
6. Каждый раз, когда добавляешь функцию, механику или экран, добавляй пакеты в docs/work_plan.json (см. протокол), иначе владелец не увидит их на портале.
7. Запреты: секреты в репозиторий и чат; действия на серверах и с деньгами владельца только по его прямой команде; слияние в main только ты.

Начни с вопросов владельцу: цель проекта, кто пользователи, какие платформы и ограничения, сроки, бюджет, что считается успехом. Затем предложи структуру репозитория и план первых этапов.
"""


def zip_bytes(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, text in sorted(files.items()):
            z.writestr(path, text)
        z.writestr("docs/WORK_PLAN.md", render_plan_md(files))
    return buf.getvalue()
