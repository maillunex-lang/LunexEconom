#!/usr/bin/env python3
"""V2 GitHub CI-gated recursive server deployment; never targets V1 defaults."""
import json
import os
import re
import stat
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = os.getenv('LUNEX_REPO', 'maillunex-lang/LunexEconom')
SERVER_DIR = Path(os.getenv('LUNEX_SERVER_DIR', '/opt/lunexeconom-v2/server'))
STATE = Path(os.getenv('LUNEX_UPDATE_STATE', '/var/lib/lunexeconom-v2-update'))
SERVICES = os.getenv('LUNEX_SERVICES', 'lunexeconom-v2.service').split()
HEALTH_URL = os.getenv('LUNEX_HEALTH_URL','http://127.0.0.1:18777/health')
OWNER = os.getenv('LUNEX_SERVER_USER','gamedev')
WORKFLOW = 'server-check.yml'
ENV_FILE = Path(os.getenv('LUNEX_ENV_FILE', '/etc/lunexeconom-v2/v2.env'))
VENV = Path(os.getenv('LUNEX_VENV', '/opt/lunexeconom-v2/venv'))
UA = {'User-Agent':'LunexEconom-V2-Updater/1', 'Accept':'application/vnd.github+json'}
MAX_FILE = 2_000_000
KEEP_BACKUPS = 5
PATH = re.compile(r'server/(?:[A-Za-z_][A-Za-z0-9_]*/)*[A-Za-z_][A-Za-z0-9_]*\.py$|server/(?:data|migrations)/(?:[A-Za-z0-9_\-]+\.)?(?:json|sql)$|server/platform/admin_ui\.html$|server/requirements\.txt$')


def safe_path(name):
    if not PATH.fullmatch(name) or '/tests/' in name or name.startswith('server/tests/') or Path(name).name.startswith('test_'):
        raise ValueError('Unsafe server file: ' + name)
    return name.removeprefix('server/')


def files_from_tree(tree):
    if tree.get('truncated'):
        raise ValueError('Truncated GitHub tree')
    names = sorted(safe_path(i['path']) for i in tree.get('tree',[]) if i.get('type')=='blob' and i.get('path','').startswith('server/') and PATH.fullmatch(i['path']) and not i['path'].startswith('server/tests/') and not Path(i['path']).name.startswith('test_'))
    if not {'game_server.py','auth.py','registry.py','__init__.py'} <= set(names):
        raise ValueError('Missing server entrypoints')
    return names


def fetch(url, limit=MAX_FILE):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as response:
        raw = response.read(limit+1)
    if len(raw)>limit: raise ValueError('Response too large')
    return raw


def api(path):
    return json.loads(fetch('https://api.github.com/repos/'+REPO+path, 3_000_000))


def validate(stage, names):
    import json as _json
    for name in names:
        data = (stage/name).read_bytes()
        if name.endswith('.py'): compile(data, name, 'exec')
        if name.endswith('.json'): _json.loads(data)


def stage_tree(commit,names,stage):
    for name in names:
        target=stage/name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(fetch(f'https://raw.githubusercontent.com/{REPO}/{commit}/server/{name}'))
    validate(stage,names)


def run(cmd):
    return subprocess.run(cmd, text=True, capture_output=True,timeout=60)


def restart():
    for service in SERVICES:
        result=run(['systemctl','restart',service])
        if result.returncode: raise RuntimeError('V2 service restart failed: '+service+' (systemctl output withheld)')


def health_sha(sha, timeout=30):
    deadline = time.monotonic() + timeout
    while True:
        try:
            d = json.loads(fetch(HEALTH_URL, 20000))
            actual = d.get('sha', '')
            if (d.get('ok') is True and d.get('database') == 'ok'
                    and isinstance(actual, str) and re.fullmatch(r'[0-9a-f]{7,40}', actual)
                    and sha.startswith(actual)):
                return True
        except (ValueError, OSError, KeyError):
            pass
        if time.monotonic() >= deadline: return False
        time.sleep(1)


def atomic_sha(sha):
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise RuntimeError('Invalid deployment SHA')
    original = ENV_FILE.read_bytes()
    matches = list(re.finditer(rb'(?m)^LUNEX_SHA=([^\r\n]*)(?=\r?$|\n)', original))
    if len(matches) != 1:
        raise RuntimeError('Expected exactly one LUNEX_SHA in V2 environment')
    old = matches[0].group(1).decode('ascii', errors='ignore')
    updated = original[:matches[0].start()] + b'LUNEX_SHA=' + sha.encode('ascii') + original[matches[0].end():]
    metadata = ENV_FILE.stat()
    fd, tmp = tempfile.mkstemp(prefix='.v2-sha-', dir=ENV_FILE.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            os.fchmod(out.fileno(), stat.S_IMODE(metadata.st_mode))
            os.fchown(out.fileno(), metadata.st_uid, metadata.st_gid)
            out.write(updated)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, ENV_FILE)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    return old


def install_requirements():
    command = ['runuser', '-u', OWNER, '--', str(VENV / 'bin' / 'python'),
               '-m', 'pip', 'install', '-r', str(SERVER_DIR / 'requirements.txt')]
    result = run(command)
    if result.returncode:
        raise RuntimeError('V2 dependency installation failed; output withheld')



def copy_tree(source,destination,names):
    for name in names:
        path=destination/name
        path.parent.mkdir(parents=True,exist_ok=True)
        tmp=path.with_name(path.name+'.new')
        shutil.copy2(source/name,tmp)
        os.replace(tmp,path)


def deploy(commit,names):
    STATE.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=STATE,prefix='stage-') as tmp:
        stage=Path(tmp)
        stage_tree(commit,names,stage)
        backup_dir=STATE/'backups'/f'{int(time.time())}-{commit[:12]}'
        backup_dir.mkdir(parents=True,exist_ok=False)
        prior=[p.relative_to(SERVER_DIR).as_posix() for p in SERVER_DIR.rglob('*') if p.is_file()] if SERVER_DIR.exists() else []
        for name in prior:
            dest=backup_dir/name
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(SERVER_DIR/name,dest)
        previous_sha = None
        changed_sha = False
        restarted = False
        requirements_changed = ('requirements.txt' in names and
            (not (SERVER_DIR / 'requirements.txt').exists() or
             (SERVER_DIR / 'requirements.txt').read_bytes() != (stage / 'requirements.txt').read_bytes()))
        try:
            SERVER_DIR.mkdir(parents=True,exist_ok=True)
            copy_tree(stage,SERVER_DIR,names)
            # Preserve files removed from upstream until a separately approved cleanup.
            # This deployment only creates or replaces V2 release files.
            if requirements_changed:
                print('Installing verified V2 requirements for', commit)
                install_requirements()
            previous_sha = atomic_sha(commit)
            changed_sha = True
            restarted = True
            restart()
            if not health_sha(commit):
                raise RuntimeError('V2 health or commit SHA mismatch after restart')
        except Exception:
            rollback_errors = []
            for name in names:
                if name not in prior:
                    try: (SERVER_DIR/name).unlink(missing_ok=True)
                    except OSError: rollback_errors.append('remove new file')
            for name in prior:
                try:
                    dest=SERVER_DIR/name
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(backup_dir/name,dest)
                except OSError:
                    rollback_errors.append('restore server file')
            if changed_sha:
                try: atomic_sha(previous_sha)
                except (OSError, RuntimeError, ValueError):
                    rollback_errors.append('restore environment SHA')
            if restarted:
                try:
                    restart()
                    if not previous_sha or not health_sha(previous_sha):
                        rollback_errors.append('rollback health or SHA mismatch')
                except Exception:
                    rollback_errors.append('restart rolled-back service')
            if rollback_errors:
                print('V2 rollback incomplete for', commit, ':', ', '.join(sorted(set(rollback_errors))), file=sys.stderr)
                raise RuntimeError('V2 rollback incomplete; inspect V2 service and state')
            print('V2 rollback restored files and SHA for', commit, file=sys.stderr)
            raise
        backups=sorted((STATE/'backups').iterdir())
        for old in backups[:-KEEP_BACKUPS]: shutil.rmtree(old)


def main():
    sha=api('/commits/main')['sha']
    if not re.fullmatch('[0-9a-f]{40}',sha): raise ValueError('Invalid SHA')
    STATE.mkdir(parents=True,exist_ok=True)
    done=STATE/'deployed-sha'
    failed=STATE/'failed-sha'
    if done.exists():
        deployed = done.read_text().strip()
        if not re.fullmatch(r'[0-9a-f]{40}', deployed) or not health_sha(deployed, timeout=2):
            raise RuntimeError('Stale V2 deployed-sha: running server SHA/health differs; no deployment')
        if deployed == sha:
            print('V2 already running', sha)
            return 0
    if failed.exists() and failed.read_text().strip()==sha: return 0
    runs=api(f'/actions/workflows/{WORKFLOW}/runs?head_sha={sha}&per_page=100')
    matching=[r for r in runs.get('workflow_runs',[]) if r.get('head_sha')==sha and r.get('event') in ('push','workflow_dispatch')]
    if not any(r.get('conclusion')=='success' for r in matching):
        print('Awaiting successful V2 server-check on',sha)
        return 0
    names=files_from_tree(api('/git/trees/'+sha+'?recursive=1'))
    try: deploy(sha,names)
    except Exception as exc:
        failed.write_text(sha+'\n')
        print('V2 deployment failed; rollback attempted for', sha, ':', type(exc).__name__, file=sys.stderr)
        return 1
    done.write_text(sha+'\n')
    print('V2 deployed',sha)
    return 0

if __name__=='__main__': sys.exit(main())
