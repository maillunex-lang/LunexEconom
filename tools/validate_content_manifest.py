"""Validate proposed content-pack manifests. Does not touch server or client."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

try:
    from manifest_security import validate_https_file_url
except ImportError:
    from tools.manifest_security import validate_https_file_url

ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = Path(__file__).resolve().parent / "sim" / "data" / "content_proposed"
REQUIRED_PRIORITY = {"ui_theme": "required"}


class ManifestError(ValueError):
    pass


def _pairs(pairs):
    item = {}
    for key, value in pairs:
        if key in item:
            raise ManifestError(f"duplicate JSON key {key!r}")
        item[key] = value
    return item


def _reject_constant(token):
    raise ManifestError(f"non-integer number {token}")


def _integers(value, path, errors):
    if isinstance(value, bool) or isinstance(value, str) or value is None:
        return
    if isinstance(value, float):
        errors.append(f"{path}: float")
        return
    if isinstance(value, int):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _integers(item, f"{path}[{index}]", errors)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _integers(item, f"{path}.{key}", errors)
        return
    errors.append(f"{path}: not an integer")


def load_limits(root=None):
    root = Path(root) if root is not None else PROPOSAL
    return json.loads(
        (root / "limits.json").read_text(encoding="utf-8"),
        object_pairs_hook=_pairs,
        parse_constant=_reject_constant,
    )


def load_schema(root=None):
    root = Path(root) if root is not None else PROPOSAL
    schema = json.loads(
        (root / "schema.json").read_text(encoding="utf-8"),
        object_pairs_hook=_pairs,
        parse_constant=_reject_constant,
    )
    Draft202012Validator.check_schema(schema)
    return schema


def load_manifest(path):
    raw = Path(path).read_bytes()
    if len(raw) > 65536:
        raise ManifestError(f"{Path(path).name}: manifest larger than 65536 bytes")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_reject_constant), raw


def _cycles(names, edges):
    visiting, visited = set(), set()
    found = []

    def visit(node, stack):
        if node in visiting:
            found.append("cycle: " + " -> ".join(stack + [node]))
            return
        if node in visited:
            return
        visiting.add(node)
        for nxt in edges.get(node, ()):
            if nxt in names:
                visit(nxt, stack + [node])
        visiting.remove(node)
        visited.add(node)

    for name in sorted(names):
        visit(name, [])
    return found


def validate_manifest(data, limits, raw_size=None, schema=None):
    errors = []
    _integers(data, "manifest", errors)
    if schema is None:
        schema = load_schema()
    for err in sorted(Draft202012Validator(schema).iter_errors(data), key=lambda item: list(item.path)):
        errors.append(f"schema: {list(err.path)}: {err.message}")
    if raw_size is not None and raw_size > limits["max_manifest_bytes"]:
        errors.append("manifest: too large")
    packs = data.get("packs")
    if not isinstance(packs, list):
        return errors
    if len(packs) > limits["max_packs"]:
        errors.append("manifest: too many packs")
    base = limits["base_url"]
    names = []
    kinds = []
    total = 0
    edges = {}
    release = data.get("release")
    for pack in packs:
        if not isinstance(pack, dict):
            errors.append("pack: not an object")
            continue
        name = pack.get("name")
        kind = pack.get("kind")
        names.append(name)
        kinds.append(kind)
        version = pack.get("version")
        if isinstance(release, int) and not isinstance(release, bool):
            if version != str(release):
                errors.append(f"{name}: version must equal release")
        if kind in REQUIRED_PRIORITY and pack.get("priority") != REQUIRED_PRIORITY[kind]:
            errors.append(f"{name}: priority must be {REQUIRED_PRIORITY[kind]}")
        if kind not in REQUIRED_PRIORITY and pack.get("priority") == "required":
            errors.append(f"{name}: only ui_theme is required")
        if kind == "season":
            if not isinstance(name, str) or not name.startswith("season_"):
                errors.append(f"{name}: season pack name must start with season_")
        elif name != kind:
            errors.append(f"{name}: name must match kind")
        size = pack.get("size")
        if type(size) is int and kind in limits["pack_bytes"] and size > limits["pack_bytes"][kind]:
            errors.append(f"{name}: size above kind limit")
        if type(size) is int:
            total += size
            if size > limits["client_pack_ceiling_bytes"]:
                errors.append(f"{name}: size above client ceiling")
        url = pack.get("url")
        expected = None
        if isinstance(name, str) and isinstance(version, str):
            expected = base.rstrip("/") + "/packs/" + name + "-" + version + ".pck"
        if not isinstance(url, str) or expected is None or url != expected or not validate_https_file_url(url, base):
            errors.append(f"{name}: url must stay on the public base")
        deps = pack.get("dependencies")
        if isinstance(deps, list):
            edges[name] = list(deps)
            if name in deps:
                errors.append(f"{name}: depends on itself")
    if len(names) != len(set(names)):
        errors.append("manifest: duplicate pack name")
    if len([k for k in kinds if k != "season"]) != len(set(k for k in kinds if k != "season")):
        errors.append("manifest: duplicate kind")
    if kinds.count("season") > 1:
        errors.append("manifest: only one season pack")
    if total > limits["max_release_bytes"]:
        errors.append("manifest: release larger than limit")
    known = set(names)
    for name, deps in edges.items():
        for dep in deps:
            if dep not in known:
                errors.append(f"{name}: missing dependency {dep}")
    errors.extend(_cycles(known, edges))
    for pack in packs:
        if isinstance(pack, dict) and type(pack.get("min_version_code")) is int:
            if pack["min_version_code"] < 1:
                errors.append(f"{pack.get('name')}: min_version_code below 1")
    return errors


def validate_limits(limits):
    errors = []
    _integers(limits, "limits", errors)
    ceiling = limits["client_pack_ceiling_bytes"]
    if limits["max_release_bytes"] > limits["cache_bytes"]:
        errors.append("limits: release bigger than cache")
    if limits["cellular_budget_bytes"] > limits["max_release_bytes"]:
        errors.append("limits: cellular budget bigger than a release")
    for kind, size in limits["pack_bytes"].items():
        if type(size) is not int or size < 1 or size > ceiling or size > limits["max_release_bytes"]:
            errors.append(f"limits: {kind} pack limit is unsafe")
    return errors


def check_tree(root=None):
    root = Path(root) if root is not None else PROPOSAL
    limits = load_limits(root)
    schema = load_schema(root)
    problems = [f"limits: {item}" for item in validate_limits(limits)]
    good = []
    for name in limits["examples_good"]:
        data, raw = load_manifest(root / name)
        errors = validate_manifest(data, limits, len(raw), schema)
        if errors:
            problems.append(f"{name}: " + "; ".join(errors))
        else:
            good.append(name)
    bad_hits = []
    for name in limits["examples_bad"]:
        data, raw = load_manifest(root / name)
        errors = validate_manifest(data, limits, len(raw), schema)
        if not errors:
            problems.append(f"{name}: expected errors, got none")
        if not any("cycle:" in item for item in errors):
            problems.append(f"{name}: expected a cycle")
        if not any("url must stay" in item for item in errors):
            problems.append(f"{name}: expected a bad url")
        bad_hits.append((name, errors))
    return problems, good, bad_hits


def main(argv=None):
    try:
        problems, good, bad = check_tree()
    except (OSError, ManifestError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if problems:
        print(f"ERROR: {len(problems)} content manifest problem(s)", file=sys.stderr)
        for line in problems:
            print(f"ERROR: {line}", file=sys.stderr)
        return 1
    print(f"good manifests: {len(good)}")
    print(f"rejected manifests: {len(bad)}")
    print("OK content manifests (no secrets, balance: draft)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
