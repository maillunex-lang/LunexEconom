#!/usr/bin/env python3
"""Read-only public GitHub -> isolated static webroot deployer. No git credentials."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

REPO = "maillunex-lang/LunexEconom"
BASE = Path("/var/www/rikagro-game/lunexeconom")
STATE = Path("/var/lib/lunexeconom-deploy")
FILES = ("index.html", "style.css", "app.js")
UA = {"User-Agent": "LunexEconom-Deploy/1.0", "Accept": "application/vnd.github+json"}
MAX_BYTES = 500_000

def fetch(url, limit=MAX_BYTES):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=18) as resp:
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise ValueError("remote content exceeds limit")
    return data

def json_api(url):
    return json.loads(fetch(url, 2_000_000))

def check_web(root):
    html = (root / "index.html").read_text("utf-8")
    js = (root / "app.js").read_text("utf-8")
    css = (root / "style.css").read_text("utf-8")
    for s in ("lang=\"ru\"", 'id="roadmap-list"', 'id="commit-list"', 'id="apk-state"'):
        if s not in html:
            raise ValueError("missing required HTML marker " + s)
    if "loadRoadmap()" not in js or "loadApk()" not in js:
        raise ValueError("dashboard entrypoints absent")
    if "https://api.github.com/repos/" not in js or len(css) < 200:
        raise ValueError("incomplete web assets")
    node = shutil.which("node")
    if node:
        subprocess.run([node, "--check", str(root / "app.js")], check=True, timeout=15)

def release_metadata():
    """Publish only verified release APK assets. No draft or prerelease filtering requirement."""
    try:
        releases = json_api("https://api.github.com/repos/" + REPO + "/releases?per_page=10")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"status": "unavailable", "version": None, "url": None, "sha256": None}
        raise
    for release in releases:
        if release.get("draft"):
            continue
        for asset in release.get("assets", []):
            name = asset.get("name", "")
            url = asset.get("browser_download_url", "")
            if not re.fullmatch(r"[A-Za-z0-9._-]+\.apk", name, re.I):
                continue
            if not url.startswith("https://github.com/" + REPO + "/releases/download/"):
                continue
            if asset.get("size", 0) < 100_000:
                continue
            # Download and inspect the APK before it can appear on the site.
            # Keep APK outside the live directory until verification completes.
            apk_dir = STATE / "apks"
            apk_dir.mkdir(parents=True, exist_ok=True)
            filename = (release["tag_name"] + "-" + name).replace("/", "_")
            dest = apk_dir / filename
            if not dest.exists() or dest.stat().st_size != asset["size"]:
                with tempfile.NamedTemporaryFile(dir=apk_dir, delete=False) as temp:
                    temp_name = Path(temp.name)
                try:
                    request = urllib.request.Request(url, headers={"User-Agent": "LunexEconom-Deploy/1.0"})
                    with urllib.request.urlopen(request, timeout=90) as response, temp_name.open("wb") as out:
                        shutil.copyfileobj(response, out, length=1024 * 1024)
                    if temp_name.stat().st_size != asset["size"]:
                        raise ValueError("APK size mismatch")
                    import zipfile
                    with zipfile.ZipFile(temp_name) as archive:
                        if archive.testzip() is not None or "AndroidManifest.xml" not in archive.namelist():
                            raise ValueError("APK archive invalid")
                    os.replace(temp_name, dest)
                finally:
                    temp_name.unlink(missing_ok=True)
            digest = hashlib.sha256(dest.read_bytes()).hexdigest()
            # Public link is the original GitHub release asset, not a guessed local path.
            return {"status": "published", "version": release["tag_name"], "url": url, "sha256": digest}
    return {"status": "unavailable", "version": None, "url": None, "sha256": None}

def main():
    STATE.mkdir(parents=True, exist_ok=True)
    # GitHub commit SHA is used to pin all downloaded website files to the same revision.
    commit = json_api("https://api.github.com/repos/" + REPO + "/commits/main")["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("invalid commit SHA")
    with tempfile.TemporaryDirectory(prefix="lunex-stage-", dir=STATE) as stage_name:
        stage = Path(stage_name)
        for name in FILES:
            (stage / name).write_bytes(fetch(f"https://raw.githubusercontent.com/{REPO}/{commit}/web/{name}"))
        check_web(stage)
        # Website assets are updated only after validation.
        # Existing live files remain available during fetch/validation failures.
        BASE.mkdir(parents=True, exist_ok=True)
        for name in FILES:
            tmp = BASE / (name + ".new")
            shutil.copy2(stage / name, tmp)
            os.chmod(tmp, 0o644)
            os.replace(tmp, BASE / name)
    (STATE / "deployed-sha").write_text(commit + "\n", encoding="utf-8")
    # Release errors must never break the working website or remove the last valid APK link.
    try:
        metadata = release_metadata()
        if metadata["status"] == "published":
            tmp = BASE / "release.json.new"
            tmp.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
            os.chmod(tmp, 0o644)
            os.replace(tmp, BASE / "release.json")
        elif not (BASE / "release.json").exists():
            (BASE / "release.json").write_text(json.dumps(metadata), encoding="utf-8")
    except Exception as e:
        print("Release check failed, retaining last release metadata:", e, file=sys.stderr)
    print("Validated and deployed commit:", commit)

if __name__ == "__main__":
    main()
