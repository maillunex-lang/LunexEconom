#!/usr/bin/env python3
"""Verify the offline, subpath-safe static landing and director-owned roadmap."""
from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
STATUSES = {"done", "wip", "planned"}
APPROVED_URLS = {
    "https://github.com/maillunex-lang/LunexEconom",
    "https://github.com/maillunex-lang/LunexEconom/releases/latest",
}


class WebsiteMarkup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.links = []
        self.paths = []
        self.lang = None
        self.title = False
        self.viewport = False
        self.images_missing_alt = []

    def handle_starttag(self, tag, pairs):
        attrs = dict(pairs)
        if tag == "html":
            self.lang = attrs.get("lang")
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "title":
            self.title = True
        if tag == "meta" and attrs.get("name") == "viewport":
            self.viewport = "width=device-width" in attrs.get("content", "")
        if tag == "img" and "alt" not in attrs:
            self.images_missing_alt.append(attrs.get("src", "<unknown>"))
        if tag == "a":
            self.links.append(attrs.get("href", ""))
        for key in ("href", "src", "poster", "action", "data"):
            if key in attrs:
                self.paths.append(attrs[key])


def valid_url(value: str) -> bool:
    if not value or value.startswith(("/", "\\", "//")) or "\\" in value:
        return False
    if re.match(r"^[a-z][a-z0-9+.-]*:", value, re.I):
        return value in APPROVED_URLS
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or any(part == ".." for part in parsed.path.split("/")):
        return False
    if re.search(r"%(?:2e|2f|5c|00)", value, re.I):
        return False
    return True


def check_roadmap(data: dict) -> None:
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise ValueError("Roadmap schema must be 1")
    for field in ("updated", "title"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ValueError(f"Missing roadmap {field}")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["updated"]):
        raise ValueError("Roadmap updated must be ISO date")
    import datetime
    datetime.date.fromisoformat(data["updated"])
    milestones = data.get("milestones")
    phases = data.get("phases")
    if not isinstance(milestones, list) or not milestones or not isinstance(phases, list) or not phases:
        raise ValueError("Milestones and phases must be nonempty arrays")
    if [m.get("id") for m in milestones if isinstance(m, dict)] != ["m0", "m1", "m2", "m3", "beta"]:
        raise ValueError("Unexpected milestones")
    ids = set()
    for milestone in milestones:
        if not isinstance(milestone, dict) or milestone.get("status") not in STATUSES or not isinstance(milestone.get("title"), str) or not milestone["title"].strip():
            raise ValueError("Invalid milestone title or status")
        ids.add(milestone["id"])
    phase_ids = set()
    for phase in phases:
        if not isinstance(phase, dict) or not isinstance(phase.get("id"), str) or not phase["id"].strip() or phase["id"] in phase_ids:
            raise ValueError("Invalid or duplicated phase id")
        phase_ids.add(phase["id"])
        if phase.get("milestone") not in ids:
            raise ValueError("Phase references unknown milestone")
        if not isinstance(phase.get("title"), str) or not phase["title"].strip() or phase.get("status") not in STATUSES:
            raise ValueError("Invalid phase title or status")
        progress = phase.get("progress")
        if type(progress) is not int or not 0 <= progress <= 100:
            raise ValueError("Progress must be integer from 0 to 100")
        items = phase.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("Phase items must be nonempty")
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("title"), str) or not item["title"].strip() or item.get("status") not in STATUSES:
                raise ValueError("Invalid phase item title or status")


def main(root: Path = ROOT):
    web = root / "web"
    html = (web / "index.html").read_text(encoding="utf-8")
    css = (web / "styles.css").read_text(encoding="utf-8")
    javascript = (web / "site.js").read_text(encoding="utf-8")
    config = (web / "config.js").read_text(encoding="utf-8")
    data = json.loads((web / "roadmap.json").read_text(encoding="utf-8"))
    check_roadmap(data)
    parser = WebsiteMarkup()
    parser.feed(html)
    assert parser.lang == "ru", "Root page must declare Russian language"
    assert parser.title and parser.viewport, "Page must include title and responsive viewport"
    assert "viewport-fit=cover" in html
    assert not parser.images_missing_alt, f"Image missing alt: {parser.images_missing_alt}"
    assert {"home", "about", "mechanics", "screens", "roadmap", "download", "install", "journal", "faq"} <= parser.ids
    assert all(link[1:] in parser.ids for link in parser.links if link.startswith("#")), "Invalid in-page link"
    assert all(valid_url(path) for path in parser.paths), "Root, unsafe or unapproved URL"
    assert "./styles.css" in parser.paths and "./site.js" in parser.paths and "./config.js" in parser.paths
    for match in re.finditer(r"url\(\s*[\"\x27]?([^\)\"\x27]+)", css, re.I):
        assert valid_url(match.group(1).strip()), "Invalid CSS url()"
    for match in re.finditer(r"@import\s+(?:url\()?\s*[\"\x27]?([^\s;\)\"\x27]+)", css, re.I):
        assert valid_url(match.group(1)), "Forbidden CSS import"
    for file in ("index.html", "styles.css", "site.js", "config.js"):
        contents = (web / file).read_text(encoding="utf-8")
        assert not re.search(r"(?:https?:)?//(?:fonts\.googleapis|fonts\.gstatic|cdn\.|unpkg\.|jsdelivr\.)", contents, re.I), "External dependency found"
    for path in re.findall(r"fetch\(\s*[\"\x27]([^\"\x27]+)", javascript):
        assert valid_url(path) and path.startswith("./"), "Fetch must be subpath-relative"
    assert "document.cookie" not in javascript and "document.cookie" not in config, "No cookies"
    assert re.search(r"LUNEX_PUBLIC_BASE\s*=\s*\"https://rikagro\.ru/lunexeconom\"", config)
    assert "prefers-reduced-motion" in css and "data-theme" in css
    assert "Capitalism Lab" not in html
    print("Website checks passed: relative paths, allowed links, content, accessible markup, roadmap")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, AssertionError, OSError, json.JSONDecodeError) as exc:
        print(f"Website checks FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
