"""Project launch wizard: validate GitHub repository identifiers and produce one prompt."""
import re
from pathlib import Path
from urllib.parse import urlsplit

PART = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,98}[A-Za-z0-9])?")
SOURCE = Path(__file__).with_name("PROJECT_LAUNCH_PROMPT.md")


def normalize_repo(value):
    if not isinstance(value, str) or len(value) > 500 or not value or value != value.strip():
        raise ValueError("invalid_repo")
    text = value
    if text.lower().startswith("https://"):
        try:
            url = urlsplit(text)
            valid = url.scheme == "https" and url.hostname == "github.com" and not url.username and not url.password and url.port is None and not url.query and not url.fragment
        except ValueError:
            raise ValueError("invalid_repo") from None
        if not valid:
            raise ValueError("invalid_repo")
        text = url.path.lstrip("/")
    elif "://" in text or text.startswith("//") or text.startswith("/"):
        raise ValueError("invalid_repo")
    # GitHub tree, blob, and trailing slash paths identify the first two components.
    if "%" in text or chr(92) in text or any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise ValueError("invalid_repo")
    items = text.split("/")
    if len(items) < 2 or any(not x for x in items[:2]):
        raise ValueError("invalid_repo")
    owner, repo = items[:2]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if (not PART.fullmatch(owner) or not PART.fullmatch(repo) or owner.startswith("-") or repo.startswith("-")
            or owner.endswith(".") or repo.endswith(".") or ".." in owner or ".." in repo or owner == "." or repo == "."):
        raise ValueError("invalid_repo")
    if len(items) > 2 and items[2:] != [""]:
        tail = items[2:]
        if tail[-1] == "":
            tail.pop()
        if any(not PART.fullmatch(t) for t in tail):
            raise ValueError("invalid_repo")
    return owner + "/" + repo


def render_prompt(name, repo, wish):
    # Single regex substitution: untrusted replacement text is never interpreted again.
    template = SOURCE.read_text(encoding="utf-8")
    if not ("{name}" in template and "{repo}" in template and "{wish}" in template):
        raise ValueError("launch_template_invalid")
    return re.sub(r"\{(name|repo|wish)\}", lambda match: {"name": name, "repo": repo or "(репозиторий не указан)", "wish": wish or "(уточнить при интервью)"}[match.group(1)], template)


def steps(plan_json):
    import json
    if plan_json is None:
        phase = 0
    else:
        try:
            phase = 2 if json.loads(plan_json).get("packages") else 1
        except (ValueError, TypeError, AttributeError):
            phase = 0
    labels = [
        ("Скопировать промпт директору", "Отправьте единый текст ИИ-директору"),
        ("Директор готовит репозиторий и план", "После подготовки директор откроет PR"),
        ("Слить PR в main", "Проверьте PR и слейте его в main"),
        ("Синхронизировать план", "Загрузите docs/work_plan.json из GitHub"),
    ]
    # Loading a plan proves step 4, not the GitHub PR merge or owner acknowledgment.
    return [{"number": i + 1, "title": t, "description": desc,
             "done": phase >= 1 and i == 3, "current": phase == 0 and i == 0}
            for i, (t, desc) in enumerate(labels)]
