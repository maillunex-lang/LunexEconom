"""Read-only release/version diagnostics; never expose environment or secrets."""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import admin, settings
from .admin_server import guard, _migrations
from server.platform.api import health
from server.catalog.overrides import read_revision


def _latest():
    path = os.getenv("LUNEX_RELEASE_META_DIR", "").strip()
    if not path:
        return None, "Путь к метаданным релиза не задан."
    root = Path(path)
    file = root / "latest.json"
    try:
        if not root.is_dir() or file.is_symlink() or not file.is_file() or file.stat().st_size>16384:
            return None, "Файл latest.json недоступен или слишком большой."
        with file.open(encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            return None,"Некорректный формат файла метаданных."
        # Whitelist only, never reflect unknown content from the file or environment.
        wanted = ("version_name","version_code","version","size","size_bytes",
                  "sha256","date","published_at","previous")
        result = {k:payload[k] for k in wanted if k in payload and
                  ((type(payload[k]) in (int, str) and len(str(payload[k]))<=128) or payload[k] is None)}
        return result, None
    except (OSError, ValueError, UnicodeError, TypeError):
        return None, "Метаданные релиза недоступны или повреждены."


def releases(body,ctx):
    actor,err=guard(ctx)
    if err:return err
    status_code,h=health({},ctx)
    defaults=ctx["registry"].flags
    active=settings.read_settings(ctx["conn"],defaults,ctx["registry"].flag_constraints)
    current={k:{"default":v,"current":active.get(k),
                "overridden":active.get(k)!=v} for k,v in sorted(defaults.items())}
    latest,explanation=_latest()
    return 200,{"version":h.get("version"),"sha":h.get("sha"),
         "migrations":_migrations(ctx["conn"]),
         "catalog":{"sha":ctx["registry"].catalog.version,
                    "revision":read_revision(ctx["conn"])},
         "flags":current,"release":latest,"release_note":explanation}
