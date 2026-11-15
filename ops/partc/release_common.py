#!/usr/bin/env python3
"""LunexEconom V2: verified, fail-closed GitHub release publishing.

Only the pinned public key is used. Never writes or requires private keys.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

REPO = 'maillunex-lang/LunexEconom'
BASE = 'https://rikagro.ru/lunexeconom/v2'
DEST = Path('/var/www/rikagro-game/lunexeconom-v2')
TOKEN = Path('/etc/lunexeconom-v2/github-token')
# This key is pinned to the current main and to the Android client. Never fetch it dynamically.
PUBKEY = Path('/etc/lunexeconom-v2/update_public.pem')
API = f'https://api.github.com/repos/{REPO}'
MAX_APK = 99 * 1024 * 1024
ASSET_MAX = 2 * 1024 * 1024


def log(msg):
    print('[vps-a2] ' + str(msg), flush=True)


def fail(msg):
    raise ValueError(str(msg))


def version_info(tag):
    m = re.fullmatch(r'v(0)\.(1)\.([0-9]{1,3})', tag)
    if not m:
        fail('not a supported alpha version tag (v0.1.N)')
    patch = int(m.group(3))
    code = 1000 + patch
    name = f'0.1.{patch}'
    if tag != 'v' + name:
        fail('non-canonical alpha version tag')
    return name, code


def checksum(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def token():
    if not TOKEN.is_file() or TOKEN.stat().st_size == 0:
        fail('read-only GitHub token missing')
    if TOKEN.stat().st_mode & 0o077:
        fail('GitHub token permissions too broad')
    t = TOKEN.read_text().strip()
    if not t or '\n' in t or '\r' in t:
        fail('invalid token file')
    return t


def request_url(url, tok=None, *, accept='application/vnd.github+json'):
    parts = urlparse(url)
    if parts.scheme != 'https' or parts.netloc not in ('api.github.com', 'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com', 'rikagro.ru'):
        fail('unexpected download host')
    headers = {'User-Agent': 'LunexEconom-VPS-A2/1', 'Accept': accept,
               'X-GitHub-Api-Version': '2022-11-28'}
    if tok and parts.netloc == 'api.github.com':
        headers['Authorization'] = 'Bearer ' + tok
    return urllib.request.Request(url, headers=headers)


def open_url(url, tok=None, *, accept='application/vnd.github+json'):
    # The redirect target (GitHub asset CDN) is intentionally not given any authorization.
    req = request_url(url, tok, accept=accept)
    return urllib.request.urlopen(req, timeout=45)


def api_json(url, tok):
    with open_url(url, tok) as r:
        if r.status != 200:
            fail('GitHub API returned non-200')
        data = r.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        fail('GitHub API response too large')
    return json.loads(data)


def github_release(tag=None):
    tok = token()
    rate = api_json('https://api.github.com/rate_limit', tok)
    remaining = int(rate['resources']['core']['remaining'])
    if remaining <= 20:
        fail('GitHub API remaining <=20')
    log(f'GitHub API remaining={remaining}')
    if tag is None:
        rel = api_json(API + '/releases/latest', tok)
    else:
        version_info(tag)
        rel = api_json(API + '/releases/tags/' + tag, tok)
    if rel.get('draft') or rel.get('prerelease'):
        fail('draft/prerelease must not be published')
    version_info(str(rel['tag_name']))
    if tag is not None and tag != rel['tag_name']:
        fail('release tag mismatch')
    return rel


def assets(release):
    result = {}
    for a in release.get('assets', []):
        name = a.get('name')
        if isinstance(name, str) and name not in result:
            result[name] = a
        elif name in result:
            fail('duplicate asset name')
    return result


def safe_asset(asset, output, limit):
    url = asset['browser_download_url']
    if not url.startswith('https://github.com/' + REPO + '/releases/download/'):
        fail('unexpected asset URL')
    claimed = int(asset.get('size', -1))
    if claimed < 1 or claimed > limit:
        fail('invalid GitHub asset size')
    count = 0
    with open_url(url, accept='application/octet-stream') as r, Path(output).open('xb') as w:
        final = urlparse(r.geturl())
        if final.scheme != 'https' or final.hostname not in ('release-assets.githubusercontent.com', 'github.com', 'objects.githubusercontent.com'):
            fail('GitHub asset redirected to unexpected host')
        if r.status != 200:
            fail('asset HTTP status not 200')
        while True:
            b = r.read(1024 * 1024)
            if not b:
                break
            count += len(b)
            if count > limit or count > claimed:
                fail('asset too large')
            w.write(b)
        w.flush()
        os.fsync(w.fileno())
    if count != claimed:
        fail('asset size mismatch')
    return count


def canonical_json(obj):
    return (json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n').encode('utf-8')


def verify_signature(manifest, signature):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    raw = Path(manifest).read_bytes()
    data = json.loads(raw)
    if raw != canonical_json(data):
        fail('manifest JSON is not canonical')
    if not PUBKEY.is_file():
        fail('pinned public key is missing')
    # Optional hard pin to the key verified against GitHub main on 2026-11-16.
    if checksum(PUBKEY) != '7589650a1dc9b2bab6b7c425e1390ffc62be9ec047baa7fae157e5ed78cf4ccd':
        fail('public key differs from pinned Android client key')
    key = serialization.load_pem_public_key(PUBKEY.read_bytes())
    sig = base64.b64decode(Path(signature).read_bytes().strip(), validate=True)
    key.verify(sig, raw, padding.PKCS1v15(), hashes.SHA256())
    return data


def validate_apk(apk, data, tag):
    version, code = version_info(tag)
    if not isinstance(data, dict):
        fail('manifest is not an object')
    if data.get('version_name') != version or type(data.get('version_code')) is not int or data['version_code'] != code:
        fail('manifest version mismatch')
    if data.get('apk_url') != f'{BASE}/download/lunex-{version}.apk':
        fail('manifest apk_url mismatch')
    size = Path(apk).stat().st_size
    if not 1 <= size <= MAX_APK or type(data.get('size')) is not int or data['size'] != size:
        fail('APK size mismatch')
    with Path(apk).open('rb') as f:
        if f.read(2) != b'PK':
            fail('APK not ZIP/PK')
    digest = checksum(apk)
    if not isinstance(data.get('sha256'), str) or data['sha256'].lower() != digest:
        fail('APK SHA-256 mismatch')
    return version, code, size, digest


def verify_sums(path, digest):
    lines = Path(path).read_text(encoding='utf-8').splitlines()
    matches = []
    for line in lines:
        m = re.fullmatch(r'([0-9a-fA-F]{64})\s+\*?(.+)', line.strip())
        if m and Path(m.group(2)).name == 'lunex.apk':
            matches.append(m.group(1).lower())
    if len(matches) != 1 or matches[0] != digest:
        fail('SHA256SUMS mismatch/missing for lunex.apk')


def download_verified_release(release, stage):
    tag = str(release['tag_name'])
    names = assets(release)
    for n in ('lunex.apk', 'update.json', 'update.json.sig', 'SHA256SUMS'):
        if n not in names:
            fail('missing GitHub release asset: ' + n)
    for n in ('update.json', 'update.json.sig', 'SHA256SUMS'):
        safe_asset(names[n], stage / n, ASSET_MAX)
    data = verify_signature(stage/'update.json', stage/'update.json.sig')
    safe_asset(names['lunex.apk'], stage/'lunex.apk', MAX_APK)
    version, code, size, digest = validate_apk(stage/'lunex.apk', data, tag)
    verify_sums(stage/'SHA256SUMS', digest)
    log(f'Verified release {tag}; signature OK; APK {size} bytes SHA256 {digest}')
    return {'version_name':version, 'version_code':code, 'size':size,
            'sha256':digest, 'apk_url':data['apk_url'], 'released': data.get('released')}


def copy_fsync(src, dst):
    # Exclusive temp file in destination filesystem, then atomic rename.
    with Path(src).open('rb') as inp, Path(dst).open('xb') as out:
        shutil.copyfileobj(inp,out,1024*1024)
        out.flush()
        os.fsync(out.fileno())
    os.chmod(dst, 0o644)


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def write_temp(data, path):
    with Path(path).open('xb') as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    os.chmod(path,0o644)


def check_public(version, size, *, check_manifests=True):
    """GET, HEAD, Range smoke. Raises if any state disagrees."""
    import urllib.request
    url = f'{BASE}/download/lunex-{version}.apk'
    req = urllib.request.Request(url, method='HEAD',headers={'Cache-Control':'no-cache','User-Agent':'LunexEconom-VPS-A2/1'})
    with urllib.request.urlopen(req,timeout=20) as r:
        if r.status != 200 or int(r.headers['Content-Length']) != size or r.headers.get_content_type() != 'application/vnd.android.package-archive':
            fail('public HEAD mismatch')
    req = urllib.request.Request(url,headers={'Range':'bytes=0-1','Cache-Control':'no-cache','User-Agent':'LunexEconom-VPS-A2/1'})
    with urllib.request.urlopen(req,timeout=20) as r:
        if r.status != 206 or r.read() != b'PK' or r.headers.get('Content-Range') != f'bytes 0-1/{size}':
            fail('public Range mismatch')
    if check_manifests:
        for name in ('update.json','update.json.sig'):
            with urllib.request.urlopen(urllib.request.Request(BASE+'/'+name,headers={'Cache-Control':'no-cache','User-Agent':'LunexEconom-VPS-A2/1'}),timeout=20) as r:
                if r.status != 200 or 'no-store' not in r.headers.get('Cache-Control',''):
                    fail('public manifest headers mismatch: '+name)
                if name == 'update.json' and r.headers.get_content_type() != 'application/json':
                    fail('public manifest Content-Type mismatch')
    log('Public HTTPS verified: HEAD 200, APK Range 206'+(', signed manifest GET 200' if check_manifests else ''))


def publish(stage, meta, rel, *, dry=False, with_latest=False):
    """Fail-closed. Signed metadata is switched as ONE symlink rename.

    versioned APK remains immutable; previous files are backed up. No private key.
    """
    version = meta['version_name']
    folder = DEST / 'download'
    destapk = folder / f'lunex-{version}.apk'
    pointer = DEST / '.signed-current'
    signed_root = DEST / '.signed-releases'
    signed_dir = signed_root / ('v' + version)
    if dry:
        log('DRY RUN: verified; no site writes')
        return
    # Never allow manual publication of an older version once a newer latest is live.
    current_latest = DEST / 'latest.json'
    if current_latest.is_file():
        current = json.loads(current_latest.read_text(encoding='utf-8'))
        if type(current.get('version_code')) is not int:
            fail('existing latest.json has invalid version_code')
        if current['version_code'] > meta['version_code']:
            fail('refusing downgrade below published latest')
    DEST.mkdir(parents=True, exist_ok=True)
    folder.mkdir(parents=True, exist_ok=True)
    signed_root.mkdir(mode=0o755, exist_ok=True)
    checkpoint = DEST / ('.release-backup-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    checkpoint.mkdir(mode=0o700)
    tracked = [folder / 'lunex.apk']
    if with_latest:
        tracked.append(DEST / 'latest.json')
    baseline = {}
    staged = {}
    applied = []
    previous_pointer = os.readlink(pointer) if pointer.is_symlink() else None
    new_signed_dir = False
    switched = False
    try:
        if pointer.exists() and not pointer.is_symlink():
            fail('signed-current exists but is not symlink')
        if previous_pointer and ('..' in Path(previous_pointer).parts or not previous_pointer.startswith('.signed-releases/')):
            fail('signed-current points outside signed-releases')
        if destapk.exists():
            if destapk.is_symlink() or not destapk.is_file() or checksum(destapk) != meta['sha256']:
                fail('versioned APK exists with different content')
        elif destapk.is_symlink():
            fail('versioned APK symlink unexpected')
        # Immutable signed release directory, never overwrite an existing one.
        if signed_dir.exists():
            if signed_dir.is_symlink() or not signed_dir.is_dir():
                fail('invalid existing signed directory')
            for n in ('update.json', 'update.json.sig'):
                if not (signed_dir / n).is_file() or checksum(signed_dir / n) != checksum(stage / n):
                    fail('existing signed release differs')
        else:
            new_signed_dir = True
            signed_dir.mkdir(mode=0o755)
            for n in ('update.json', 'update.json.sig'):
                copy_fsync(stage / n, signed_dir / n)
            sync_dir(signed_dir)
            sync_dir(signed_root)
        # The service runs with UMask=0077, so mkdir(mode=...) alone leaves 0700 and nginx
        # answers 403. Set world-readable modes explicitly, also for a directory left by an
        # earlier failed run.
        os.chmod(signed_root, 0o755)
        os.chmod(signed_dir, 0o755)
        for n in ('update.json', 'update.json.sig'):
            os.chmod(signed_dir / n, 0o644)
        for i, p in enumerate(tracked):
            if p.is_symlink() or (p.exists() and not p.is_file()):
                fail('non-regular tracked file')
            baseline[p] = p.exists()
            if p.exists():
                copy_fsync(p, checkpoint / f'{i}.bak')
        todo = [(folder / 'lunex.apk', stage / 'lunex.apk')]
        if with_latest:
            previous = json.loads((DEST / 'latest.json').read_text()) if (DEST / 'latest.json').exists() else None
            old_code = previous.get('version_code', -1) if isinstance(previous, dict) else -1
            if type(old_code) is not int or old_code > meta['version_code']:
                fail('release older than latest')
            if old_code == meta['version_code'] and previous and previous.get('sha256') != meta['sha256']:
                fail('same version changed digest')
            if isinstance(previous, dict) and old_code == meta['version_code']:
                older = previous.get('previous')
            else:
                older = previous
            latest = dict(schema=1, channel='alpha', version_name=version,
                          version_code=meta['version_code'], released=meta['released'] or rel.get('published_at'),
                          apk_url=meta['apk_url'], size=meta['size'], sha256=meta['sha256'],
                          notes=rel.get('body') or '', previous=older)
            latestbytes = canonical_json(latest)
            if len(latestbytes) > 1024 * 1024:
                fail('latest.json too large')
            write_temp(latestbytes, stage / 'latest.json')
            todo.append((DEST / 'latest.json', stage / 'latest.json'))
        # Every live target has its own staged temp on the SAME destination filesystem.
        for target, source in todo:
            temp = target.with_name('.' + target.name + '.vps-a2-' + checkpoint.name + '.new')
            copy_fsync(source, temp)
            staged[target] = temp
        temp_pointer = DEST / ('.signed-current-' + checkpoint.name + '.new')
        temp_pointer.symlink_to('.signed-releases/v' + version)
        if not destapk.exists():
            tmp_apk = folder / ('.' + destapk.name + '.' + checkpoint.name + '.new')
            copy_fsync(stage / 'lunex.apk', tmp_apk)
            try:
                os.link(tmp_apk, destapk)
            finally:
                tmp_apk.unlink(missing_ok=True)
            sync_dir(folder)
        # Commit steps: versioned APK, alias, ONE atomic pointer swap, then latest.json.
        alias = folder / 'lunex.apk'
        os.replace(staged[alias], alias)
        applied.append(alias)
        sync_dir(folder)
        os.replace(temp_pointer, pointer)
        switched = True
        sync_dir(DEST)
        if with_latest:
            latest_target = DEST / 'latest.json'
            os.replace(staged[latest_target], latest_target)
            applied.append(latest_target)
            sync_dir(DEST)
        check_public(version, meta['size'], check_manifests=True)
        # Download the public pair and compare their exact signed bytes.
        for n in ('update.json', 'update.json.sig'):
            req = urllib.request.Request(BASE + '/' + n, headers={'Cache-Control': 'no-cache', 'User-Agent': 'LunexEconom-VPS-A2/1'})
            with urllib.request.urlopen(req, timeout=20) as response:
                if response.read() != (stage / n).read_bytes():
                    fail('public signed metadata mismatch: ' + n)
        log('PUBLISH VERIFIED v' + version)
    except BaseException:
        log('ERROR; rolling back changed live pointers/files; keeping immutable historical releases')
        for target in reversed(applied):
            i = tracked.index(target)
            if baseline.get(target):
                os.replace(checkpoint / f'{i}.bak', target)
            else:
                target.unlink(missing_ok=True)
            sync_dir(target.parent)
        if switched:
            if previous_pointer is None:
                pointer.unlink(missing_ok=True)
            else:
                tmp_restore = DEST / ('.signed-restore-' + checkpoint.name)
                tmp_restore.symlink_to(previous_pointer)
                os.replace(tmp_restore, pointer)
            sync_dir(DEST)
        raise
    finally:
        for temp in staged.values():
            temp.unlink(missing_ok=True)
        if 'temp_pointer' in locals():
            temp_pointer.unlink(missing_ok=True)
        log('Backup retained: ' + str(checkpoint))


def run(tag=None, dry=False, sync=False):
    if os.geteuid()!=0:
        fail('run as root (needed for protected token and destination)')
    if not PUBKEY.is_file():
        fail('public key not installed')
    rel=github_release(tag)
    tag=rel['tag_name']
    log('Release '+tag+' (published, non-prerelease)')
    # Already-verified releases are immutable. Avoid repeatedly downloading the APK.
    if sync and not dry:
        latest_path = DEST / 'latest.json'
        pointer = DEST / '.signed-current'
        if latest_path.is_file() and pointer.is_symlink():
            try:
                previous = json.loads(latest_path.read_text(encoding='utf-8'))
                current_version, expected_code = version_info(tag)
                apk = DEST / 'download' / f'lunex-{current_version}.apk'
                sig_dir = DEST / '.signed-releases' / ('v' + current_version)
                if (previous.get('version_name') == current_version
                        and previous.get('version_code') == expected_code
                        and os.readlink(pointer) == '.signed-releases/v' + current_version
                        and (sig_dir / 'update.json').is_file()
                        and (sig_dir / 'update.json.sig').is_file()
                        and apk.is_file()):
                    data = verify_signature(sig_dir / 'update.json', sig_dir / 'update.json.sig')
                    _, _, size, digest = validate_apk(apk, data, tag)
                    if (previous.get('sha256') == digest and previous.get('size') == size
                            and previous.get('apk_url') == data['apk_url']):
                        log('Already published and locally re-verified '+tag+'; no download or file changes')
                        return
            except (ValueError, OSError, KeyError, TypeError) as exc:
                log('Current local publication needs fresh verification: ' + type(exc).__name__)
    with tempfile.TemporaryDirectory(prefix='lunex-vps-a2-') as td:
        stage=Path(td)
        meta=download_verified_release(rel,stage)
        publish(stage,meta,rel,dry=dry,with_latest=sync)


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--tag',default=None)
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--sync',action='store_true')
    args=parser.parse_args()
    try:
        run(tag=args.tag,dry=args.dry_run,sync=args.sync)
    except Exception as e:
        # Errors must not contain token/authorization; only a short reason, no HTTP body.
        log('FAILED: '+type(e).__name__+': '+str(e)[:180])
        sys.exit(1)