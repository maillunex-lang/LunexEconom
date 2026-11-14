#!/usr/bin/env python3
"""Auto-deploy of the LunexEconom Python game server from public GitHub `main`.

Runs on the VPS from a systemd timer. No git credentials, no SSH from GitHub.
Safety rules:
  * deploy only a commit whose GitHub Actions "Server checks" run succeeded;
  * download files pinned to that exact commit SHA;
  * byte-compile everything (no code is executed here) before touching live files;
  * back up the live files, restart the service, verify /health;
  * on any failure restore the backup, restart again and remember the bad SHA
    so the same commit is not retried in a loop.
Configuration comes from environment variables (see below); defaults match docs/SERVER_DEPLOYMENT.md.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = os.environ.get("LUNEX_REPO", "maillunex-lang/LunexEconom")
SERVER_DIR = Path(os.environ.get("LUNEX_SERVER_DIR", "/home/gamedev/projects/LunexEconom-server"))
STATE = Path(os.environ.get("LUNEX_UPDATE_STATE", "/var/lib/lunexeconom-server-update"))
SERVICES = os.environ.get("LUNEX_SERVICES", "lunexeconom-game.service").split()
HEALTH_URL = os.environ.get("LUNEX_HEALTH_URL", "http://127.0.0.1:18767/health")
OWNER = os.environ.get("LUNEX_SERVER_USER", "gamedev")
WORKFLOW = "server-check.yml"
UA = {"User-Agent": "LunexEconom-ServerUpdate/1.0", "Accept": "application/vnd.github+json"}
MAX_FILE = 300_000
KEEP_BACKUPS = 10
SERVER_FILE = re.compile(r"server/([A-Za-z0-9_]+\.py)")


def fetch(url, limit=MAX_FILE):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as resp:
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise ValueError("remote content exceeds limit: " + url)
    return data


def api(path):
    return json.loads(fetch("https://api.github.com/repos/" + REPO + path, 3_000_000))


def server_files(commit):
    """Runtime server modules at `commit` (tests are not deployed)."""
    tree = api("/git/trees/" + commit + "?recursive=1")
    if tree.get("truncated"):
        raise ValueError("git tree truncated")
    names = []
    for item in tree["tree"]:
        m = SERVER_FILE.fullmatch(item.get("path", ""))
        if m and item.get("type") == "blob" and not m.group(1).startswith("test_"):
            names.append(m.group(1))
    if not {"game_server.py", "auth.py"} <= set(names):
        raise ValueError("server tree is missing required modules")
    return sorted(names)


def validate(stage, names):
    for name in names:
        compile((stage / name).read_bytes(), name, "exec")  # syntax check only, nothing is executed


def run(cmd):
    return subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=60)


def restart():
    for unit in SERVICES:
        result = run(["systemctl", "restart", unit])
        if result.returncode != 0:
            raise RuntimeError("restart failed for " + unit + ": " + result.stderr.strip())


def healthy(timeout=30):
    if not HEALTH_URL:
        return True
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=3) as resp:
                if resp.status == 200 and json.loads(resp.read()).get("ok") is True:
                    return True
        except Exception:
            pass
        time.sleep(1.5)
    return False


def install(stage, names, target):
    for name in names:
        tmp = target / (name + ".new")
        shutil.copy2(stage / name, tmp)
        os.chmod(tmp, 0o644)
        try:
            shutil.chown(tmp, OWNER, OWNER)
        except (LookupError, PermissionError):
            pass
        os.replace(tmp, target / name)


def backup(names, target, backups):
    dest = backups / time.strftime("%Y%m%d-%H%M%S")
    dest.mkdir(parents=True)
    for name in names:
        if (target / name).exists():
            shutil.copy2(target / name, dest / name)
    for old in sorted(p for p in backups.iterdir() if p.is_dir())[:-KEEP_BACKUPS]:
        shutil.rmtree(old, ignore_errors=True)
    return dest


def deploy(commit, names):
    backups = STATE / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stage-", dir=STATE) as tmp:
        stage = Path(tmp)
        for name in names:
            (stage / name).write_bytes(fetch("https://raw.githubusercontent.com/%s/%s/server/%s" % (REPO, commit, name)))
        validate(stage, names)
        saved = backup(names, SERVER_DIR, backups)
        try:
            install(stage, names, SERVER_DIR)
            restart()
            if not healthy():
                raise RuntimeError("health check failed after restart")
        except Exception:
            # Roll back files that existed before; remove files that are new in this commit.
            for name in names:
                if (saved / name).exists():
                    shutil.copy2(saved / name, SERVER_DIR / name)
                else:
                    (SERVER_DIR / name).unlink(missing_ok=True)
            try:
                restart()
            finally:
                raise


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    commit = api("/commits/main")["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("invalid commit SHA")
    deployed = STATE / "deployed-sha"
    failed = STATE / "failed-sha"
    if deployed.exists() and deployed.read_text().strip() == commit:
        print("up to date:", commit)
        return 0
    if failed.exists() and failed.read_text().strip() == commit:
        print("commit previously failed to deploy, waiting for a new commit:", commit)
        return 0
    names = server_files(commit)
    # The server files changed only if the server-check workflow ran for this commit.
    runs = api("/actions/workflows/" + WORKFLOW + "/runs?head_sha=" + commit + "&per_page=20")
    seen = [r for r in runs.get("workflow_runs", []) if r.get("head_sha") == commit]
    if not seen:
        # No server-related change in this commit: nothing new to deploy for the server.
        deployed.write_text(commit + "\n")
        print("no server checks for", commit, "- marked as current")
        return 0
    if not any(r.get("conclusion") == "success" for r in seen):
        pending = any(r.get("status") != "completed" for r in seen)
        print("CI gate", "pending" if pending else "failed", "for", commit, "- keeping current server")
        return 0
    try:
        deploy(commit, names)
    except Exception as exc:
        failed.write_text(commit + "\n")
        print("DEPLOY FAILED, rolled back:", exc, file=sys.stderr)
        return 1
    deployed.write_text(commit + "\n")
    print("deployed", commit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
