#!/usr/bin/env python3
"""V2 GitHub CI-gated recursive server deployment; never targets V1 defaults."""
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

REPO = os.getenv('LUNEX_REPO', 'maillunex-lang/LunexEconom')
SERVER_DIR = Path(os.getenv('LUNEX_SERVER_DIR', '/opt/lunexeconom-v2/server'))
STATE = Path(os.getenv('LUNEX_UPDATE_STATE', '/var/lib/lunexeconom-v2-update'))
SERVICES = os.getenv('LUNEX_SERVICES', 'lunexeconom-v2.service').split()
HEALTH_URL = os.getenv('LUNEX_HEALTH_URL','http://127.0.0.1:18777/health')
OWNER = os.getenv('LUNEX_SERVER_USER','gamedev')
WORKFLOW = 'server-check.yml'
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
        if result.returncode: raise RuntimeError('Restart failed: '+service+' '+result.stderr.strip())


def healthy(timeout=30):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            if json.loads(fetch(HEALTH_URL,20000)).get('ok') is True: return True
        except Exception: pass
        time.sleep(1)
    return False


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
        try:
            SERVER_DIR.mkdir(parents=True,exist_ok=True)
            copy_tree(stage,SERVER_DIR,names)
            for name in prior:
                if name not in names and (name.endswith(('.py','.json','.sql','.html')) or name=='requirements.txt'):
                    (SERVER_DIR/name).unlink(missing_ok=True)
            restart()
            if not healthy(): raise RuntimeError('V2 health check failed')
        except Exception:
            for name in names:
                if name not in prior: (SERVER_DIR/name).unlink(missing_ok=True)
            for name in prior:
                dest=SERVER_DIR/name
                dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(backup_dir/name,dest)
            restart()
            raise
        backups=sorted((STATE/'backups').iterdir())
        for old in backups[:-KEEP_BACKUPS]: shutil.rmtree(old)


def main():
    sha=api('/commits/main')['sha']
    if not re.fullmatch('[0-9a-f]{40}',sha): raise ValueError('Invalid SHA')
    STATE.mkdir(parents=True,exist_ok=True)
    done=STATE/'deployed-sha'
    failed=STATE/'failed-sha'
    if done.exists() and done.read_text().strip()==sha: return 0
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
        print('Rollback completed after error:',exc,file=sys.stderr)
        return 1
    done.write_text(sha+'\n')
    print('V2 deployed',sha)
    return 0

if __name__=='__main__': sys.exit(main())
