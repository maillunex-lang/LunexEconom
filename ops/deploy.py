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
    releases.sort(key=lambda r: r.get("tag_name") != "android-test-latest")
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
            stamp = apk_dir / (filename + ".asset-id")
            current_id = str(asset.get("id", ""))
            if not dest.exists() or dest.stat().st_size != asset["size"] or not stamp.exists() or stamp.read_text() != current_id:
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
                    stamp.write_text(current_id)
                finally:
                    temp_name.unlink(missing_ok=True)
            digest = hashlib.sha256(dest.read_bytes()).hexdigest()
            # Publish the verified APK from our VPS, not GitHub's login-gated artifacts.
            BASE.mkdir(parents=True, exist_ok=True)
            public_name = "Bashkiria-Honey-Oil-debug.apk" if release["tag_name"] == "android-test-latest" else name
            public_path = BASE / public_name
            if not public_path.exists() or hashlib.sha256(public_path.read_bytes()).hexdigest() != digest:
                with tempfile.NamedTemporaryFile(dir=BASE, delete=False) as staged:
                    staged_name = Path(staged.name)
                try:
                    shutil.copyfile(dest, staged_name)
                    os.chmod(staged_name, 0o644)
                    os.replace(staged_name, public_path)
                finally:
                    staged_name.unlink(missing_ok=True)
            channel = "debug" if release["tag_name"] == "android-test-latest" else "release"
            metadata = {"status": "published", "version": release["tag_name"],
                        "url": "https://rikagro.ru/lunexeconom/" + public_name,
                        "sha256": digest, "channel": channel, "tested_on_device": False}
            if channel == "release":
                build_assets = [a for a in release.get("assets", []) if a.get("name") == "build_info.json"]
                if len(build_assets) != 1:
                    continue  # Older releases lack verified version metadata.
                info_url = build_assets[0].get("browser_download_url", "")
                if not info_url.startswith("https://github.com/" + REPO + "/releases/download/"):
                    continue
                build = json.loads(fetch(info_url, 8192))
                metadata.update(version_code=build.get("version_code"),
                                version_name=build.get("version_name"), size=asset["size"])
                # The Android updater requires this exact HTTPS versions/ origin.
                versions = BASE / "versions"
                versions.mkdir(parents=True, exist_ok=True)
                version_path = versions / name
                if not version_path.exists() or hashlib.sha256(version_path.read_bytes()).hexdigest() != digest:
                    with tempfile.NamedTemporaryFile(dir=versions, delete=False) as staged:
                        tmp_version = Path(staged.name)
                    try:
                        shutil.copyfile(dest, tmp_version)
                        os.chmod(tmp_version, 0o644)
                        os.replace(tmp_version, version_path)
                    finally:
                        tmp_version.unlink(missing_ok=True)
                metadata["url"] = "https://rikagro.ru/lunexeconom/versions/" + name
            return metadata
    return {"status": "unavailable", "version": None, "url": None, "sha256": None}


def publish_update_manifest(metadata):
    """Atomically publish only signed, versioned release metadata for Android updater.

    Debug artifacts remain visible on the landing page but never enter the updater.
    No network requests here; callers provide validated release metadata.
    """
    if metadata.get("status") != "published" or metadata.get("channel") != "release":
        return False
    code = metadata.get("version_code")
    version = metadata.get("version_name")
    sha = metadata.get("sha256")
    url = metadata.get("url")
    size = metadata.get("size")
    if (type(code) is not int or code < 1 or not isinstance(version, str)
            or not re.fullmatch(r"[0-9A-Za-z._+-]{1,40}", version)
            or not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha)
            or not isinstance(size, int) or size <= 0 or size > 160 * 1024 * 1024
            or not isinstance(url, str)
            or not re.fullmatch(r"https://rikagro\\.ru/lunexeconom/versions/[A-Za-z0-9._-]+\\.apk", url)):
        raise ValueError("invalid signed release metadata for updater")
    target = BASE / "updates" / "manifest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        previous = json.loads(target.read_text(encoding="utf-8"))
        old = previous.get("apk", {})
        old_code = int(old.get("version_code", 0))
        if code < old_code or (code == old_code and old.get("sha256") != sha):
            raise ValueError("update rollback or conflicting version code rejected")
    payload = {"schema": 1, "apk": {"version_code": code, "version_name": version,
                                     "url": url, "sha256": sha, "size": size}}
    with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, prefix=".manifest-",
                                     encoding="utf-8", delete=False) as staged:
        staged_name = Path(staged.name)
        json.dump(payload, staged, ensure_ascii=False)
        staged.write("\\n")
    try:
        os.chmod(staged_name, 0o644)
        os.replace(staged_name, target)
    finally:
        staged_name.unlink(missing_ok=True)
    return True

def main():
    STATE.mkdir(parents=True, exist_ok=True)
    # GitHub commit SHA is used to pin all downloaded website files to the same revision.
    commit = json_api("https://api.github.com/repos/" + REPO + "/commits/main")["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("invalid commit SHA")
    # Require a successful GitHub Actions validation for this exact commit.
    runs = json_api("https://api.github.com/repos/" + REPO +
                    "/actions/workflows/website-check.yml/runs?head_sha=" + commit + "&per_page=20")
    approved = any(run.get("head_sha") == commit and run.get("event") == "push"
                   and run.get("conclusion") == "success" for run in runs.get("workflow_runs", []))
    if not approved:
        print("CI gate pending or failed for", commit, "- keeping current site")
    if approved:
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
            publish_update_manifest(metadata)
        elif not (BASE / "release.json").exists():
            (BASE / "release.json").write_text(json.dumps(metadata), encoding="utf-8")
    except Exception as e:
        print("Release check failed, retaining last release metadata:", e, file=sys.stderr)
    print("Validated and deployed commit:", commit)

if __name__ == "__main__":
    main()
