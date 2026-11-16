"""Подключение неизменяемого ядра памяти к SQLite и HTTP."""
import hashlib
import json
import os
import secrets
import time
import urllib.parse
from pathlib import Path
from ..memory import context, decisions, repomap, search
from ..memory.redact import redact

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
    return base

def repo_items(conn,slug,root):
    cached=conn.execute("SELECT items,updated FROM repo_map_cache WHERE project_slug=?",(slug,)).fetchone()
    if cached and time.time()-cached['updated']<3600:
        return json.loads(cached['items'])
    if root is None:
        return json.loads(cached['items']) if cached else []
    items=repomap.scan(root)
    items=[dict(i,about=redact(i['about'])) for i in items]
    conn.execute("INSERT INTO repo_map_cache(project_slug,items,updated) VALUES(?,?,?) ON CONFLICT(project_slug) DO UPDATE SET items=excluded.items,updated=excluded.updated",(slug,json.dumps(items,ensure_ascii=False),time.time()))
    return items

def sync_decisions(conn,slug,root):
    if root is None:
        return
    path=root/'docs/gdd/DECISIONS_APPROVED.md'
    if not path.is_file():
        return
    for entry in decisions.parse_markdown(path.read_text(encoding='utf-8')[:300000]):
        conn.execute("INSERT OR IGNORE INTO project_decisions(project_slug,id,date,title,text,source) VALUES(?,?,?,?,?,?)",(slug,entry['id'],entry['date'],redact(entry['title']),redact(entry['text']),entry['source']))

def decision_list(conn,slug):
    return [dict(r) for r in conn.execute("SELECT id,date,title,text,source FROM project_decisions WHERE project_slug=? ORDER BY rowid",(slug,))]

def build_context(conn,row,role='director',maximum=6000,root=None):
    slug=row['slug']
    sync_decisions(conn,slug,root)
    states={r['pkg_id']:dict(r) for r in conn.execute("SELECT pkg_id,status FROM task_state WHERE project_slug=?",(slug,))}
    lessons=[]
    try:
        item=conn.execute("SELECT content FROM project_lessons WHERE project_slug=?",(slug,)).fetchone()
        if item:lessons=json.loads(item[0])
    except Exception:pass
    events=[{'text':r['kind']+' '+(r['pkg_id'] or '')} for r in conn.execute("SELECT kind,pkg_id FROM events WHERE project_slug=? ORDER BY id DESC LIMIT 8",(slug,))]
    prs=[{'number':r['pr_number'],'title':r['pkg_id'],'ci':r['ci_state']} for r in conn.execute("SELECT pr_number,pkg_id,ci_state FROM pr_links WHERE project_slug=? AND state='open' LIMIT 10",(slug,))]
    return redact(context.build(dict(row),json.loads(row['plan_json'] or '{"packages":[]}'),states,decision_list(conn,slug),lessons,events,prs,repo_items(conn,slug,root),role,max_chars=maximum))[:maximum]

def consume(conn,token):
    digest=hashlib.sha256(token.encode()).hexdigest()
    cur=conn.execute("UPDATE context_links SET requests=requests+1 WHERE token_hash=? AND revoked=0 AND expires>? AND requests<10",(digest,time.time()))
    if not cur.rowcount:return None
    row=conn.execute("SELECT context_text FROM context_links WHERE token_hash=?",(digest,)).fetchone()
    return redact(row[0]) if row else None

def dispatch(conn,row,sub,method,environ,read_body,repo_root,base):
    slug=row['slug']
    root=root_for(row,repo_root)
    params=urllib.parse.parse_qs(environ.get('QUERY_STRING','')[:2048])
    def param(k,default=''):return params.get(k,[default])[0]
    if sub=='/context' and method=='GET':
        role=param('role','director')
        if role not in context.ROLES:raise ValueError('role')
        maximum=int(param('max','6000'))
        if not 200<=maximum<=6000:raise ValueError('max')
        return '200 OK',{'text':build_context(conn,row,role,maximum,root)}
    if sub=='/repo-map' and method=='GET':
        return '200 OK',{'items':repo_items(conn,slug,root)[:3000]}
    if sub=='/decisions':
        if method=='GET':
            sync_decisions(conn,slug,root)
            return '200 OK',{'decisions':decision_list(conn,slug)}
        if method=='POST':
            body=read_body(environ)
            if not isinstance(body,dict) or set(body)!={'title','text'} or any(type(v)!=str for v in body.values()):raise ValueError('body')
            current=decision_list(conn,slug)
            updated,entry=decisions.add(current,redact(body['title']),body['text'])
            if entry:
                conn.execute("INSERT INTO project_decisions(project_slug,id,date,title,text,source) VALUES(?,?,?,?,?,?)",(slug,entry['id'],entry['date'],redact(entry['title']),entry['text'],entry['source']))
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
        for d in decision_list(conn,slug):docs.append({'id':d['id'],'kind':'decision','title':d['title'],'text':d['text'],'url':''})
        for i,r in enumerate(conn.execute("SELECT text FROM ideas WHERE project_slug=? LIMIT 300",(slug,))):docs.append({'id':str(i),'kind':'idea','title':'Идея','text':redact(r[0]),'url':''})
        for r in conn.execute("SELECT pkg_id,body FROM task_reports WHERE project_slug=? LIMIT 200",(slug,)):docs.append({'id':r[0],'kind':'report','title':r[0],'text':redact(r[1]),'url':''})
        return '200 OK',{'results':[dict(x,type=x['kind']) for x in search.search(search.build(docs),q,limit=20,kinds=[kind] if kind else None)]}
    if sub=='/context-link' and method=='POST':
        body=read_body(environ)
        if not isinstance(body,dict):raise ValueError('body')
        if set(body)=={'revoke'}:
            token=body['revoke']
            if type(token)!=str or len(token)>128:raise ValueError('revoke')
            conn.execute("UPDATE context_links SET revoked=1 WHERE token_hash=? AND project_slug=?",(hashlib.sha256(token.encode()).hexdigest(),slug))
            return '200 OK',{'revoked':True}
        if not set(body).issubset({'role'}) or body.get('role','director') not in context.ROLES:raise ValueError('role')
        token=secrets.token_urlsafe(16)
        digest=hashlib.sha256(token.encode()).hexdigest()
        value=build_context(conn,row,body.get('role','director'),6000,root)
        expires=time.time()+86400
        conn.execute("INSERT INTO context_links(token_hash,project_slug,context_text,expires,created) VALUES(?,?,?,?,?)",(digest,slug,value,expires,time.time()))
        return '200 OK',{'url':base+'/ctx/'+token,'token':token,'expires':expires}
    return None
