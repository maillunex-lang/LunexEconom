"""GitHub read-only polling and complete check-run gate."""
from __future__ import annotations
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from portal.hooks import github

REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA = re.compile(r"^[0-9a-f]{40}$")

def github_get(url, token="", etag=None):
    if not url.startswith("https://api.github.com/"):
        raise ValueError("invalid GitHub URL")
    headers = {"Accept":"application/vnd.github+json","User-Agent":"CreatePortal-A5","X-GitHub-Api-Version":"2022-11-28"}
    if token: headers["Authorization"]="Bearer "+token
    if etag: headers["If-None-Match"]=etag
    req=urllib.request.Request(url,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=10) as response:
            data=response.read(1_000_001)
            if len(data)>1_000_000: raise ValueError("response_too_large")
            return json.loads(data),response.headers.get("ETag")
    except urllib.error.HTTPError as error:
        if error.code==304: return None,etag
        raise ValueError("github_http_error") from None

def read_token(path):
    if not path: return ""
    p=Path(path)
    if not p.is_file() or p.stat().st_mode & 0o077: raise ValueError("token_file_permissions")
    return p.read_text().strip()

def complete_checks(repo, sha, token, fetch=github_get):
    """Fail closed when checks are missing, paginated, incomplete, or unsuccessful."""
    if not REPO.fullmatch(repo) or not SHA.fullmatch(sha): return False
    total=0
    for page in range(1,11):
        url=f"https://api.github.com/repos/{repo}/commits/{sha}/check-runs?per_page=100&page={page}"
        data,_=fetch(url,token,None)
        if not isinstance(data,dict) or not isinstance(data.get("check_runs"),list): return False
        runs=data["check_runs"]
        if not runs and page==1:return False
        total+=len(runs)
        if any(r.get("status")!="completed" or r.get("conclusion") not in ("success","neutral","skipped") for r in runs):return False
        if len(runs)<100:
            if data.get("total_count",total)>total:return False
            return total>0
    return False

def guarded_process(conn, kind, payload, delivery, *, fetch_plan=None, token="", fetch=github_get):
    """Suppress legacy auto-accept until every GitHub check-run has been verified."""
    repo=(payload.get("repository") or {}).get("full_name","")
    projects=conn.execute("SELECT slug FROM projects WHERE repo=?",(repo,)).fetchall() if REPO.fullmatch(repo) else []
    saved=[]
    for row in projects:
        slug=row["slug"]
        setting=conn.execute("SELECT auto_accept,auto_accept_require_checklist,required_checks FROM project_settings WHERE project_slug=?",(slug,)).fetchone()
        saved.append((slug,dict(setting) if setting else None))
        conn.execute("INSERT INTO project_settings(project_slug,auto_accept) VALUES(?,0) ON CONFLICT(project_slug) DO UPDATE SET auto_accept=0",(slug,))
    try:
        result=github.process(conn,kind,payload,delivery,fetch_plan=fetch_plan)
    finally:
        for slug,setting in saved:
            if setting is None:conn.execute("DELETE FROM project_settings WHERE project_slug=?",(slug,))
            else:conn.execute("UPDATE project_settings SET auto_accept=?,auto_accept_require_checklist=?,required_checks=? WHERE project_slug=?",
                              (setting["auto_accept"],setting["auto_accept_require_checklist"],setting["required_checks"],slug))
    for slug,_ in saved:
        for link in conn.execute("SELECT sha FROM pr_links WHERE project_slug=? AND state='merged'",(slug,)).fetchall():
            if complete_checks(repo,link["sha"],token,fetch):
                github.reconcile(conn,slug)
    return result

def poll_project(conn, slug, token, fetch=github_get, now=None):
    now=time.time() if now is None else now
    row=conn.execute("SELECT repo,branch,sync_mode,poll_minutes FROM projects WHERE slug=?",(slug,)).fetchone()
    if not row or row["sync_mode"] not in ("polling","both") or not REPO.fullmatch(row["repo"]):return 0
    old=conn.execute("SELECT etag FROM project_sync WHERE project_slug=?",(slug,)).fetchone()
    etag=old["etag"] if old else None
    url=f'https://api.github.com/repos/{row["repo"]}/pulls?state=closed&base={urllib.parse.quote(row["branch"],safe="")}&sort=updated&direction=desc&per_page=30'
    try:
        prs,new_etag=fetch(url,token,etag)
        if prs is None:prs=[]
        if not isinstance(prs,list) or len(prs)>30:raise ValueError("invalid_pull_list")
        count=0
        for pr in prs:
            if not isinstance(pr,dict) or not pr.get("merged_at"):continue
            sha=pr.get("merge_commit_sha")
            if not isinstance(sha,str) or not SHA.fullmatch(sha):continue
            head=pr.get("head",{});base=pr.get("base",{})
            if not isinstance(head,dict) or not isinstance(base,dict):continue
            # Same normalization as webhook processor, same dedup by delivery.
            normalized={"repository":{"full_name":row["repo"]},"number":pr.get("number"),
                "action":"closed","pull_request":{"head":{"ref":head.get("ref"),"sha":head.get("sha"),"repo":{"full_name":row["repo"]}},
                "base":{"ref":row["branch"],"repo":{"full_name":row["repo"]}},"title":pr.get("title",""),"merged":True,"merge_commit_sha":sha}}
            delivery="poll-"+hashlib.sha256(f'{slug}:{pr.get("number")}:{sha}'.encode()).hexdigest()[:40]
            result=guarded_process(conn,"pull_request",normalized,delivery,token=token,fetch=fetch)
            if result=="processed":count+=1
            checks_url=f'https://api.github.com/repos/{row["repo"]}/commits/{sha}/check-runs?per_page=100'
            data,_=fetch(checks_url,token,None)
            if isinstance(data,dict) and isinstance(data.get("check_runs"),list):
                for run in data["check_runs"][:100]:
                    if not isinstance(run,dict):continue
                    ident=str(run.get("id",""))[:100]
                    if not ident:continue
                    state="pending" if run.get("status")!="completed" else ("success" if run.get("conclusion") in ("success","neutral","skipped") else "failure")
                    conn.execute("INSERT INTO ci_checks(project_slug,sha,kind,run_id,state,updated) VALUES(?,?,?,?,?,?) ON CONFLICT(project_slug,sha,kind,run_id) DO UPDATE SET state=excluded.state,updated=excluded.updated",(slug,sha,"poll_check",ident,state,now))
                # Only reconcile after complete list; avoid accepting partial check-runs.
                if complete_checks(row["repo"],sha,token,fetch):
                    github.reconcile(conn,slug)
        conn.execute("INSERT INTO project_sync(project_slug,last_poll,etag,error) VALUES(?,?,?,'') ON CONFLICT(project_slug) DO UPDATE SET last_poll=excluded.last_poll,etag=excluded.etag,error=''",(slug,now,new_etag))
        return count
    except (ValueError,TypeError,KeyError,OSError) as exc:
        conn.execute("INSERT INTO project_sync(project_slug,last_poll,error) VALUES(?,?,'poll_failed') ON CONFLICT(project_slug) DO UPDATE SET last_poll=excluded.last_poll,error='poll_failed'",(slug,now))
        return 0
