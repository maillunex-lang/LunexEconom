"""Подключение неизменяемого ядра памяти к SQLite и HTTP."""
import hashlib
import json
import os
import re
import urllib.request
import urllib.error
import secrets
import time
import urllib.parse
from pathlib import Path
from ..memory import context, decisions, repomap, search
from .. import db as portal_db
from ..backup.sync import github_get, read_token
from ..memory.redact import redact as core_redact

# Keep core untouched; add a conservative boundary filter for short assignments
# not recognized by the engine's high-confidence secret patterns.
ASSIGNMENT = re.compile(
    r'(?i)\b(password|passwd|pwd|passphrase|token|secret|api[_-]?key|private[_-]?key|пароль|токен|секрет)\s*[:=]\s*([^\s,;]+)'
)
def redact(text):
    return ASSIGNMENT.sub(lambda m: m.group(1)+'=[скрыто]', core_redact(text))

def ensure_tables(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS project_decisions(project_slug TEXT NOT NULL,id TEXT NOT NULL,date TEXT NOT NULL,title TEXT NOT NULL,text TEXT NOT NULL,source TEXT NOT NULL,PRIMARY KEY(project_slug,id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS context_links(token_hash TEXT PRIMARY KEY,project_slug TEXT NOT NULL,context_text TEXT NOT NULL,expires REAL NOT NULL,revoked INTEGER NOT NULL DEFAULT 0,requests INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS repo_map_cache(project_slug TEXT PRIMARY KEY,items TEXT NOT NULL,updated REAL NOT NULL)""")

def root_for(row, root):
    if not root:
        return None
    base=Path(root).resolve()
    # Never interpolate untrusted project names into filesystem paths.
    if not (base/'.git').is_dir():
        return None
    # A shared clone must never expose a different project's documents.
    config=base/'.git'/'config'
    try:
        import configparser
        parser=configparser.RawConfigParser()
        parser.read(config,encoding='utf-8')
        remote=parser.get('remote "origin"','url',fallback='')
        remote=remote.rstrip('/').removesuffix('.git')
        remote=remote.split('github.com/')[-1] if 'github.com/' in remote else remote.split('github.com:')[-1]
        if remote!=row['repo']:
            return None
    except (OSError,ValueError):
        return None
    return base

REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MAX_GITHUB_ITEMS = 3000

def github_tree(repo, branch='main', token_file=None, fetch=github_get):
    """Bounded GitHub read-only tree lookup; never follows arbitrary hosts."""
    if not REPO.fullmatch(repo) or any(part in (".","..") for part in repo.split("/")):
        return []
    if not re.fullmatch(r"[A-Za-z0-9._/-]{1,120}",branch or "") or ".." in branch:
        return []
    try:
        token=read_token(token_file)
        url="https://api.github.com/repos/"+repo+"/git/trees/"+urllib.parse.quote(branch,safe="")+'?recursive=1'
        payload,_=fetch(url,token,None)
        if not isinstance(payload,dict) or payload.get('truncated') or not isinstance(payload.get('tree'),list):
            return []
        if len(payload['tree'])>MAX_GITHUB_ITEMS:
            return []
        items=[]
        for entry in payload['tree']:
            if not isinstance(entry,dict) or entry.get('type')!='blob':
                continue
            name=entry.get('path')
            if not isinstance(name,str) or not name or name.startswith('/') or any(p in ('..','.git','node_modules','.venv','__pycache__') for p in name.split('/')):
                continue
            if Path(name).suffix.lower() in repomap.SKIP_EXT:
                continue
            size=entry.get('size',0)
            if not isinstance(size,int) or size<0:
                continue
            items.append({'path':name[:250],'size':size,'about':''})
        return items
    except (OSError,ValueError,TypeError,KeyError,urllib.error.URLError):
        return []

UNSAFE_FILENAMES = {'.env','.env.local','.env.production','id_rsa','id_ed25519'}
UNSAFE_SUFFIXES = {'.pem','.key','.p12','.pfx','.db','.sqlite3'}

def safe_scan(root, limit=3000):
    """Use core description extractor but never read symlinks outside the clone."""
    items=[]
    root=Path(root).resolve()
    for directory, folders, files in os.walk(root, followlinks=False):
        folders[:]=[x for x in sorted(folders) if x not in repomap.SKIP_DIRS
                    and not (Path(directory)/x).is_symlink()]
        for name in sorted(files):
            if len(items)>=limit:
                return items
            p=Path(directory)/name
            if p.is_symlink() or name in UNSAFE_FILENAMES or p.suffix.lower() in (repomap.SKIP_EXT|UNSAFE_SUFFIXES):
                continue
            if not p.resolve().is_relative_to(root):
                continue
            try:
                size=p.stat().st_size
            except OSError:
                continue
            about=''
            if size<=repomap.MAX_FILE_BYTES and p.suffix.lower() in ('.py','.md','.sh','.js','.html','.gd','.json','.service','.conf'):
                try:
                    about=redact(repomap.describe(p.relative_to(root).as_posix(),p.read_text(encoding='utf-8',errors='ignore')))
                except OSError:
                    about=''
            items.append({'path':p.relative_to(root).as_posix(),'size':size,'about':about})
    return items


def repo_items(conn,slug,root,repo='',branch='main',token_file=None,fetch=github_get):
    cached=conn.execute("SELECT items,updated FROM repo_map_cache WHERE project_slug=?",(slug,)).fetchone()
    if cached and time.time()-cached['updated']<3600:
        return json.loads(cached['items'])
    if root is not None:
        items=safe_scan(root)
    else:
        items=github_tree(repo,branch,token_file,fetch)
    items=[dict(i,about=redact(i.get('about',''))) for i in items]
    if items:
        conn.execute("INSERT INTO repo_map_cache(project_slug,items,updated) VALUES(?,?,?) ON CONFLICT(project_slug) DO UPDATE SET items=excluded.items,updated=excluded.updated",(slug,json.dumps(items,ensure_ascii=False),time.time()))
        return items
    return json.loads(cached['items']) if cached else []
def remote_documents(conn, slug, repo, branch, token_file=None, fetch=github_get):
    """Bounded, redacted document index for repositories without local clones.

    Up to 48 markdown files are indexed on the first search and reused for an hour.
    Query has a predictable upper bound even when a GitHub repository is enormous.
    """
    items=repo_items(conn,slug,None,repo,branch,token_file,fetch)
    if not items:
        return [], False
    paths=[item for item in items if item.get('path')=='README.md' or
           (item.get('path','').startswith('docs/') and item.get('path','').endswith('.md'))]
    paths.sort(key=lambda i:(i['path']!='README.md', i['path']))
    selected=paths[:48]
    pending=[item for item in selected if 'doc_text' not in item and not item.get('doc_error')]
    if pending:
        try:
            token=read_token(token_file)
        except (OSError,ValueError):
            token=''
        for entry in pending:
            path=entry['path']
            url='https://api.github.com/repos/'+repo+'/contents/'+urllib.parse.quote(path,safe='/')+'?ref='+urllib.parse.quote(branch,safe='')
            try:
                data,_=fetch(url,token,None)
                if isinstance(data,dict) and data.get('encoding')=='base64':
                    import base64
                    raw=base64.b64decode(data.get('content',''),validate=True)
                    if len(raw)>200000:raise ValueError('file_too_large')
                    entry['doc_text']=redact(raw.decode('utf-8','replace')[:20000])
                elif isinstance(data,str) and len(data.encode('utf-8'))<=200000:
                    entry['doc_text']=redact(data[:20000])
                else:
                    entry['doc_error']=True
            except (OSError,ValueError,TypeError,urllib.error.URLError):
                entry['doc_error']=True
        conn.execute("UPDATE repo_map_cache SET items=?,updated=? WHERE project_slug=?",
                     (json.dumps(items,ensure_ascii=False),time.time(),slug))
    docs=[{'id':it['path'],'kind':'document','title':Path(it['path']).stem,
           'text':it['doc_text'],'url':it['path']} for it in selected if 'doc_text' in it]
    return docs, len(paths)>len(selected)


def read_decisions_source(root,repo,branch,token_file,fetch):
    if root is not None:
        paths=[root/'DECISIONS.md',root/'docs/DECISIONS.md',root/'docs/gdd/DECISIONS_APPROVED.md']
        for path in paths:
            if path.is_file() and path.stat().st_size<=300000:
                yield path.relative_to(root).as_posix(),path.read_text(encoding='utf-8',errors='replace')
        return
    if not REPO.fullmatch(repo):
        return
    try:
        token=read_token(token_file)
    except (OSError,ValueError):
        return
    for path in ('DECISIONS.md','docs/DECISIONS.md','docs/gdd/DECISIONS_APPROVED.md'):
        url="https://api.github.com/repos/"+repo+"/contents/"+path+"?ref="+urllib.parse.quote(branch,safe="")
        try:
            data,_=fetch(url,token,None)
            if isinstance(data,str) and len(data.encode('utf-8'))<=300000:
                yield path,data
            elif isinstance(data,dict) and data.get('encoding')=='base64':
                import base64
                raw=base64.b64decode(data.get('content',''),validate=True)
                if len(raw)<=300000:
                    yield path,raw.decode('utf-8','replace')
        except (OSError,ValueError,TypeError,urllib.error.URLError):
            continue


def sync_decisions(conn,slug,root=None,repo='',branch='main',token_file=None,fetch=github_get):
    """Idempotent import; preserves owner decisions when source changes."""
    seen=set()
    for source,raw in read_decisions_source(root,repo,branch,token_file,fetch):
        parsed=decisions.parse_markdown(raw)
        if not parsed and source.endswith('DECISIONS_APPROVED.md'):
            # Approved decisions are a markdown table rather than '- ' bullets.
            for line in raw.splitlines():
                if not line.startswith('|') or line.startswith('|-----'):
                    continue
                parts=[p.strip() for p in line.strip('|').split('|')]
                if len(parts)<3 or not parts[0].startswith('D-'):
                    continue
                parsed.append({'id':parts[0],'date':'','title':parts[0],'text':redact(parts[1]+' '+parts[2])[:700],'source':source})
        for entry in parsed:
            title=redact(entry['title'])
            body=redact(entry['text'])
            if not entry['id'].startswith('D-'):
                entry['id']='repo:'+source+':'+entry['id']
            key=(entry['id'],title,body)
            if key in seen:
                continue
            seen.add(key)
            # Owner-created D1 etc must never be overwritten by an import.
            conn.execute("INSERT OR IGNORE INTO project_decisions(project_slug,id,date,title,text,source) VALUES(?,?,?,?,?,?)",(slug,entry['id'],entry['date'],title,body,source))


def decision_list(conn,slug):
    return [dict(r) for r in conn.execute("SELECT id,date,title,text,source FROM project_decisions WHERE project_slug=? ORDER BY rowid DESC LIMIT 300",(slug,))][::-1]

def build_context(conn,row,role='director',maximum=6000,root=None,token_file=None,fetch=github_get):
    slug=row['slug']
    sync_decisions(conn,slug,root,row['repo'],row['branch'],token_file,fetch)
    states={r['pkg_id']:dict(r) for r in conn.execute("SELECT pkg_id,status FROM task_state WHERE project_slug=?",(slug,))}
    lessons=[]
    try:
        item=conn.execute("SELECT content FROM project_lessons WHERE project_slug=?",(slug,)).fetchone()
        if item:lessons=json.loads(item[0])
    except Exception:pass
    events=[{'text':r['kind']+' '+(r['pkg_id'] or '')} for r in conn.execute("SELECT kind,pkg_id FROM events WHERE project_slug=? ORDER BY id DESC LIMIT 8",(slug,))]
    prs=[{'number':r['pr_number'],'title':r['pkg_id'],'ci':r['ci_state']} for r in conn.execute("SELECT pr_number,pkg_id,ci_state FROM pr_links WHERE project_slug=? AND state='open' LIMIT 10",(slug,))]
    return redact(context.build(dict(row),json.loads(row['plan_json'] or '{"packages":[]}'),states,decision_list(conn,slug),lessons,events,prs,repo_items(conn,slug,root,row['repo'],row['branch'],token_file,fetch),role,max_chars=maximum))[:maximum]

def consume(conn,token):
    digest=hashlib.sha256(token.encode()).hexdigest()
    cur=conn.execute("UPDATE context_links SET requests=requests+1 WHERE token_hash=? AND revoked=0 AND expires>? AND requests<10",(digest,time.time()))
    if not cur.rowcount:return None
    row=conn.execute("SELECT context_text FROM context_links WHERE token_hash=?",(digest,)).fetchone()
    if row:
        project=conn.execute("SELECT project_slug FROM context_links WHERE token_hash=?",(digest,)).fetchone()
        if project:portal_db.audit(conn,'memory.link.view',{'slug':project[0]})
    return redact(row[0]) if row else None

def dispatch(conn,row,sub,method,environ,read_body,repo_root,base,token_file=None,fetch=github_get):
    slug=row['slug']
    root=root_for(row,repo_root)
    params=urllib.parse.parse_qs(environ.get('QUERY_STRING','')[:2048])
    def param(k,default=''):return params.get(k,[default])[0]
    if sub=='/context' and method=='GET':
        role=param('role','director')
        if role not in context.ROLES:raise ValueError('role')
        maximum=int(param('max','6000'))
        if not 200<=maximum<=6000:raise ValueError('max')
        return '200 OK',{'text':build_context(conn,row,role,maximum,root,token_file,fetch)}
    if sub=='/repo-map' and method=='GET':
        return '200 OK',{'items':[{k:i.get(k) for k in ('path','size','about')} for i in repo_items(conn,slug,root,row['repo'],row['branch'],token_file,fetch)[:3000]]}
    if sub=='/decisions':
        if method=='GET':
            sync_decisions(conn,slug,root,row['repo'],row['branch'],token_file,fetch)
            return '200 OK',{'decisions':decision_list(conn,slug)}
        if method=='POST':
            body=read_body(environ)
            if not isinstance(body,dict) or set(body)!={'title','text'} or any(type(v)!=str for v in body.values()):raise ValueError('body')
            current=decision_list(conn,slug)
            updated,entry=decisions.add(current,redact(body['title']),redact(body['text']))
            if entry:
                conn.execute("INSERT INTO project_decisions(project_slug,id,date,title,text,source) VALUES(?,?,?,?,?,?)",(slug,entry['id'],entry['date'],redact(entry['title']),entry['text'],entry['source']))
                portal_db.audit(conn,'memory.decision.add',{'slug':slug})
            return '200 OK',{'decisions':updated,'added':entry is not None}
    if sub=='/search' and method=='GET':
        q=param('q').strip()
        if not 2<=len(q)<=100:raise ValueError('q')
        kind=param('kind')
        if kind and kind not in ('document','decision','report','lesson','idea'):raise ValueError('kind')
        docs=[]
        if root:
            for p in list((root/'docs').rglob('*.md'))[:350] + [root/'README.md']:
                if p.is_file() and p.stat().st_size<=200000:
                    rel=p.relative_to(root).as_posix()
                    docs.append({'id':rel,'kind':'document','title':p.stem,'text':redact(p.read_text(encoding='utf-8',errors='replace')[:20000]),'url':rel})
        partial=False
        if root is None:
            remote,partial=remote_documents(conn,slug,row['repo'],row['branch'],token_file,fetch)
            docs.extend(remote)
        sync_decisions(conn,slug,root,row['repo'],row['branch'],token_file,fetch)
        for d in decision_list(conn,slug):docs.append({'id':d['id'],'kind':'decision','title':d['title'],'text':d['text'],'url':''})
        for i,r in enumerate(conn.execute("SELECT text FROM ideas WHERE project_slug=? LIMIT 300",(slug,))):docs.append({'id':str(i),'kind':'idea','title':'Идея','text':redact(r[0]),'url':''})
        for r in conn.execute("SELECT pkg_id,body FROM task_reports WHERE project_slug=? LIMIT 200",(slug,)):docs.append({'id':r[0],'kind':'report','title':r[0],'text':redact(r[1]),'url':''})
        for r in conn.execute("SELECT content FROM project_lessons WHERE project_slug=?",(slug,)):
            for lesson in json.loads(r[0])[:100]:
                if isinstance(lesson,dict):docs.append({'id':str(lesson.get('id','')),'kind':'lesson','title':'Правило проекта','text':redact(str(lesson.get('text',''))),'url':''})
        for r in conn.execute("SELECT pkg_id,reasons,note FROM task_returns WHERE project_slug=? LIMIT 200",(slug,)):
            docs.append({'id':r['pkg_id'],'kind':'lesson','title':'Возврат '+r['pkg_id'],'text':redact(r['reasons']+' '+r['note']),'url':''})
        for r in conn.execute("SELECT content FROM project_prompt_library WHERE project_slug=?",(slug,)):
            for prompt in json.loads(r[0])[:100]:
                if isinstance(prompt,dict):docs.append({'id':str(prompt.get('id','')),'kind':'document','title':str(prompt.get('title','Промпт')),'text':redact(str(prompt.get('text',''))),'url':''})
        return '200 OK',{'results':[dict(x,type=x['kind']) for x in search.search(search.build(docs),q,limit=20,kinds=[kind] if kind else None)],'partial_index':partial}
    if sub=='/context-link' and method=='POST':
        body=read_body(environ)
        if not isinstance(body,dict):raise ValueError('body')
        if set(body)=={'revoke'}:
            token=body['revoke']
            if type(token)!=str or len(token)>128:raise ValueError('revoke')
            conn.execute("UPDATE context_links SET revoked=1 WHERE token_hash=? AND project_slug=?",(hashlib.sha256(token.encode()).hexdigest(),slug))
            portal_db.audit(conn,'memory.link.revoke',{'slug':slug})
            return '200 OK',{'revoked':True}
        if not set(body).issubset({'role'}) or body.get('role','director') not in context.ROLES:raise ValueError('role')
        token=secrets.token_urlsafe(16)
        digest=hashlib.sha256(token.encode()).hexdigest()
        value=build_context(conn,row,body.get('role','director'),6000,root,token_file,fetch)
        expires=time.time()+86400
        conn.execute("INSERT INTO context_links(token_hash,project_slug,context_text,expires,created) VALUES(?,?,?,?,?)",(digest,slug,value,expires,time.time()))
        portal_db.audit(conn,'memory.link.create',{'slug':slug})
        return '200 OK',{'url':base+'/ctx/'+token,'token':token,'expires':expires}
    return None
