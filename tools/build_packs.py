#!/usr/bin/env python3
"""Deterministic Godot resource packs from client/content/<name>/ source folders.

Runs Godot --export-pack for .pck when possible; no executable .gd/.tscn supplied
in resource packs. Files are staged with fixed order and deterministic timestamps.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

SUPPORTED = {".glb", ".png", ".webp", ".jpg", ".jpeg", ".ogg", ".wav", ".mp3", }
MAX_ASSET = 60 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[1]


def discover(source):
    found = []
    for item in sorted(Path(source).rglob("*")):
        if item.is_symlink():
            raise ValueError("Symlinks are not allowed in content packs")
        if item.is_file():
            if item.suffix.lower() not in SUPPORTED or item.stat().st_size > MAX_ASSET:
                raise ValueError(f"Unexpected/oversized asset: {item}")
            found.append(item)
    return found


def build(source, output, version, base_url, godot):
    from manifest_security import sha256, validate_https_file_url, canonical_json
    if not version or not all(c.isalnum() or c in "._-" for c in version):
        raise ValueError("Invalid pack version")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": 1, "packs": []}
    for directory in sorted(Path(source).iterdir()):
        if not directory.is_dir() or directory.name.startswith("."):
            continue
        name = directory.name
        if not name.isascii() or not all(ch.islower() or ch.isdigit() or ch in "_-" for ch in name):
            raise ValueError("Invalid pack name")
        files = discover(directory)
        if not files:
            continue
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "project.godot").write_text('config_version=5\n[application]\nconfig/name="pack"\n')
            for item in files:
                destination = project / "content" / name / item.relative_to(directory)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(item.read_bytes())
            # Godot pack exporter with include_filter adds ALL content resources to the .pck.
            export = project / "export_presets.cfg"
            export.write_text('[preset.0]\nname="pack"\nplatform="Android"\nrunnable=false\nexport_filter="all_resources"\ninclude_filter=""\nexclude_filter=""\n[preset.0.options]\n')
            path = output / f"{name}-{version}.pck"
            cmd = [godot, "--headless", "--path", str(project), "--editor", "--quit"]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            subprocess.run([godot, "--headless", "--path", str(project), "--export-pack", "pack", str(path)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        url = base_url.rstrip("/") + "/packs/" + path.name
        if not validate_https_file_url(url, base_url):
            raise ValueError("Invalid base URL")
        manifest["packs"].append({"name": name, "version": version, "size": path.stat().st_size,
                                  "sha256": sha256(path), "url": url,
                                  "priority": "required" if name.startswith("core_") else "background",
                                  "dependencies": [], "min_version_code": 1})
    (output / "content.json").write_bytes(canonical_json(manifest))
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="client/content")
    ap.add_argument("--output", default="build/packs")
    ap.add_argument("--version", required=True)
    ap.add_argument("--base", default=None)
    ap.add_argument("--godot", default="godot")
    args = ap.parse_args()
    print(json.dumps(build(args.source, args.output, args.version, (args.base or __import__("project_urls").public_base()), args.godot), ensure_ascii=False))
