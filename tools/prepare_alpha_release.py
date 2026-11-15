#!/usr/bin/env python3
"""Prepare an UNSIGNED alpha update manifest and an audit report; never handle keys."""
import argparse
import json
import tempfile
import urllib.request
from pathlib import Path
from make_update_manifest import ALPHA_BASE, make
from manifest_security import canonical_json
from release_version import parse

MAX_NOTES = 300


def notes_from_file(path, tag):
    data = Path(path).read_text(encoding='utf-8')
    # The shared notes file contains examples, not verified release announcements.
    if '## Шаблон' in data and '## Примеры' in data:
        # This shared file is currently only a template: accept explicitly approved
        # release-specific text, never silently reuse examples as real changelog.
        title = f'## Релиз {tag[1:]}'
        if title not in data.splitlines():
            raise ValueError('No approved release notes for ' + tag + '; provide --notes')
        text = data.split(title, 1)[1].split('\n## ', 1)[0].strip()
    else:
        text = data.strip()
    if not 1 <= len(text) <= MAX_NOTES:
        raise ValueError('Release notes must contain 1..300 characters')
    return text


def prepare(tag, apk, note, min_code, output, previous_tag=None):
    code, name = parse(tag)
    if not tag.startswith('v0.1.'):
        raise ValueError('Alpha release tag must match v0.1.N')
    if min_code is None:
        min_code = parse(previous_tag)[0] if previous_tag else max(1, code - 1)
    manifest = make(apk, tag, min_code, note, ALPHA_BASE, f'lunex-{name}.apk')
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(canonical_json(manifest))
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', required=True)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--apk')
    src.add_argument('--asset-url')
    notes = ap.add_mutually_exclusive_group(required=True)
    notes.add_argument('--notes')
    notes.add_argument('--notes-file')
    ap.add_argument('--min-code', type=int)
    ap.add_argument('--previous-tag')
    ap.add_argument('--output', default='build/update.json')
    args = ap.parse_args()
    note = args.notes if args.notes is not None else notes_from_file(args.notes_file, args.tag)
    if not 1 <= len(note) <= MAX_NOTES:
        ap.error('Notes must be 1..300 characters')
    with tempfile.TemporaryDirectory() as folder:
        if args.apk:
            apk = Path(args.apk)
        else:
            # Only owner-approved GitHub release assets; reject redirects to foreign origins.
            from urllib.parse import urlparse
            u = urlparse(args.asset_url)
            if u.scheme != 'https' or u.hostname not in ('github.com', 'release-assets.githubusercontent.com') or u.username or u.password or u.query or u.fragment:
                ap.error('Asset URL must be an approved GitHub HTTPS download')
            apk = Path(folder)/'release.apk'
            opener=urllib.request.build_opener()
            with opener.open(urllib.request.Request(args.asset_url,headers={'User-Agent':'LunexAlphaPrep'}),timeout=45) as r, apk.open('wb') as fd:
                final=urlparse(r.geturl())
                if final.scheme!='https' or final.hostname not in ('github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'):
                    ap.error('Unsafe asset redirect')
                while block:=r.read(1024*1024):
                    fd.write(block)
                    if fd.tell() > 99 * 1024 * 1024:
                        ap.error('APK exceeds 99 MiB')
        result=prepare(args.tag,apk,note,args.min_code,args.output,args.previous_tag)
    print(json.dumps({'manifest':args.output,'version_name':result['version_name'],'version_code':result['version_code'],
                      'min_version_code':result['min_version_code'],'apk_url':result['apk_url'],'size':result['size'],
                      'sha256':result['sha256'],'signed':False},ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()
