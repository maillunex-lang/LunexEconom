"""A7 adapters around the immutable, director-approved portal.review functions.

Fail closed: missing GitHub data is yellow; no PR writes are attempted here.
"""
import json
import re
import time
import urllib.request
from portal.review import engine, conflicts, knowledge, library, returns, project_types
from portal.backup.sync import read_token

MAX_DIFF = 2_000_000
REPO = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')

def plan_of(project):
    return json.loads(project['plan_json']) if project['plan_json'] else None

def pkg_of(plan, pid):
    return next((p for p in plan.get('packages', []) if p['id'] == pid), None) if plan else None

def zone_of(plan, pkg):
    lane=plan.get('lanes',{}).get(pkg.get('lane'),{})
    return list(lane.get('zone',[]))+list(pkg.get('zone_extra',[]))

def lessons(conn,slug):
    row=conn.execute('SELECT content FROM project_lessons WHERE project_slug=?',(slug,)).fetchone()
    return json.loads(row['content']) if row else []

def save_lessons(conn,slug,items):
    conn.execute('INSERT INTO project_lessons(project_slug,content) VALUES(?,?) ON CONFLICT(project_slug) DO UPDATE SET content=excluded.content',(slug,json.dumps(items,ensure_ascii=False)))

def prompt_for(conn,slug,plan,pkg):
    from tools import work_plan as wp
    text=wp.prompt(plan,pkg['id'])
    parts=[knowledge.render(lessons(conn,slug))]
    row=conn.execute('SELECT content FROM project_prompt_library WHERE project_slug=?',(slug,)).fetchone()
    examples=json.loads(row['content']) if row else []
    parts.append(library.render_examples(library.similar(examples,pkg['title'],pkg.get('goal',''),pkg.get('lane'))))
    return text+'\n\n'+'\n\n'.join(x for x in parts if x) if any(parts) else text

def github_json(url,token='',max_bytes=MAX_DIFF):
    if not url.startswith('https://api.github.com/repos/'):
        raise ValueError('github_url_invalid')
    headers={'Accept':'application/vnd.github+json','User-Agent':'CreatePortal-A7'}
    if token:headers['Authorization']='Bearer '+token
    with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=12) as response:
        raw=response.read(max_bytes+1)
    if len(raw)>max_bytes:raise ValueError('github_response_too_large')
    return json.loads(raw)

def github_diff(url,token=''):
    if not url.startswith('https://api.github.com/repos/'):
        raise ValueError('github_url_invalid')
    headers={'Accept':'application/vnd.github.v3.diff','User-Agent':'CreatePortal-A7'}
    if token:headers['Authorization']='Bearer '+token
    with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=12) as response:
        raw=response.read(MAX_DIFF+1)
    if len(raw)>MAX_DIFF:raise ValueError('diff_too_large')
    return raw.decode('utf-8','replace')

def evaluate(conn,slug,pid,project,token_file=None,fetch_json=None,fetch_diff=None,now=None):
    now=time.time() if now is None else now
    plan=plan_of(project);pkg=pkg_of(plan,pid)
    if not pkg:raise ValueError('task_not_found')
    link=conn.execute('SELECT * FROM pr_links WHERE project_slug=? AND pkg_id=? ORDER BY updated DESC LIMIT 1',(slug,pid)).fetchone()
    ci=link['ci_state'] if link else 'pending'
    checklist=conn.execute('SELECT items FROM task_reviews WHERE project_slug=? AND pkg_id=?',(slug,pid)).fetchone()
    report=conn.execute('SELECT body FROM task_reports WHERE project_slug=? AND pkg_id=?',(slug,pid)).fetchone()
    items=[{'text':x['text'],'done':x.get('checked') is True} for x in json.loads(checklist['items'])] if checklist else []
    files=[];stats=[];diff='';error=None
    if not link:error='PR ещё не привязан к задаче'
    elif not REPO.fullmatch(project['repo']):error='Некорректный репозиторий'
    else:
        try:
            token=read_token(token_file)
            jf=fetch_json or github_json;df=fetch_diff or github_diff
            root=f'https://api.github.com/repos/{project["repo"]}/pulls/{link["pr_number"]}'
            # Explicit pagination and a hard cap: incomplete listings cannot be green.
            for page in range(1,11):
                response=jf(root+f'/files?per_page=100&page={page}',token)
                if not isinstance(response,list) or len(response)>100:raise ValueError('invalid_pr_files')
                for f in response:
                    if not isinstance(f,dict) or not isinstance(f.get('filename'),str):raise ValueError('invalid_file')
                    files.append(f['filename'])
                    stats.append({'path':f['filename'],'added':f.get('additions',0),'deleted':f.get('deletions',0)})
                if len(response)<100:break
            else:raise ValueError('too_many_files')
            if not files:raise ValueError('no_pr_files')
            diff=df(root,token)
            if not isinstance(diff,str) or len(diff.encode('utf-8'))>MAX_DIFF:raise ValueError('diff_too_large')
        except (OSError,ValueError,TypeError,KeyError,UnicodeError):
            error='GitHub не вернул полный список файлов или дифф (лимит 2 МБ)'
    result=engine.review(zone_of(plan,pkg),plan.get('rules',{}).get('shared_files_director_only',[]),files,diff,stats,ci,items,report['body'] if report else '')
    if error:
        # Cannot trust a green result when evidence is incomplete. Existing red findings remain red.
        result=engine.verdict(result['checks']+[{'id':'github','status':'yellow','title':'Данные GitHub неполные','details':[error]}])
    result.update({'task_id':pid,'files':files[:1000],'stats':stats[:1000],'pr_number':link['pr_number'] if link else None,
                   'suggested_reasons':returns.reasons_from_review(result),'checked_at':now,'auto_merge_allowed':engine.auto_merge_allowed(result) and not error})
    conn.execute('INSERT INTO task_review_runs(project_slug,pkg_id,verdict,created) VALUES(?,?,?,?)',(slug,pid,json.dumps(result,ensure_ascii=False),now))
    conn.execute('INSERT INTO events(project_slug,pkg_id,ts,kind,source,payload) VALUES(?,?,?,?,?,?)',(slug,pid,now,'task.traffic_light','a7',json.dumps({'status':result['status']})))
    return result

def conflicts_for(conn,slug,plan):
    if not plan:return []
    states={r['pkg_id']:r['status'] for r in conn.execute('SELECT pkg_id,status FROM task_state WHERE project_slug=?',(slug,))}
    done={k for k,v in states.items() if v=='accepted'}
    tasks=[]
    for p in plan['packages']:
        status=states.get(p['id'],'planned')
        if status not in ('issued','submitted') and not(status=='planned' and all(x in done for x in p['depends_on'])):continue
        link=conn.execute('SELECT pr_number FROM pr_links WHERE project_slug=? AND pkg_id=? ORDER BY updated DESC LIMIT 1',(slug,p['id'])).fetchone()
        latest=conn.execute('SELECT verdict FROM task_review_runs WHERE project_slug=? AND pkg_id=? ORDER BY id DESC LIMIT 1',(slug,p['id'])).fetchone()
        files=json.loads(latest['verdict']).get('files',[]) if latest and link else []
        tasks.append({'id':p['id'],'zone':zone_of(plan,p),'files':files,'status':status})
    return conflicts.warnings(tasks)

def record_success(conn,slug,pkg,plan):
    review=conn.execute('SELECT revision_count FROM task_reviews WHERE project_slug=? AND pkg_id=?',(slug,pkg['id'])).fetchone()
    count=review['revision_count'] if review else 0
    row=conn.execute('SELECT content FROM project_prompt_library WHERE project_slug=?',(slug,)).fetchone()
    current=json.loads(row['content']) if row else []
    updated=library.record(current,pkg['id'],pkg['title'],pkg.get('goal',''),prompt_for(conn,slug,plan,pkg),count,pkg['lane'])
    conn.execute('INSERT INTO project_prompt_library(project_slug,content) VALUES(?,?) ON CONFLICT(project_slug) DO UPDATE SET content=excluded.content',(slug,json.dumps(updated,ensure_ascii=False)))

def schedule(conn,slug,pid,verdict,now=None):
    """Schedule only, never merge synchronously from a GET request."""
    now=time.time() if now is None else now
    cfg=conn.execute('SELECT * FROM project_a7_settings WHERE project_slug=?',(slug,)).fetchone()
    if not cfg or not cfg['auto_merge'] or cfg['kill_switch'] or not engine.auto_merge_allowed(verdict):return False
    state=conn.execute('SELECT status FROM task_state WHERE project_slug=? AND pkg_id=?',(slug,pid)).fetchone()
    if not state or state['status']!='submitted':return False
    pr=conn.execute("SELECT pr_number,ci_state,state FROM pr_links WHERE project_slug=? AND pkg_id=? ORDER BY updated DESC LIMIT 1",(slug,pid)).fetchone()
    if not pr or pr['state']!='open' or pr['ci_state']!='success':return False
    conn.execute('INSERT INTO task_auto_merge(project_slug,pkg_id,pr_number,due_at,cancelled) VALUES(?,?,?,?,0) ON CONFLICT(project_slug,pkg_id) DO NOTHING',(slug,pid,pr['pr_number'],now+cfg['auto_merge_delay_minutes']*60))
    return True

def merge_request(url,token,sha):
    """Squash with head-SHA precondition to prevent merging unreviewed changes."""
    import urllib.error
    body=json.dumps({'merge_method':'squash','sha':sha}).encode('utf-8')
    headers={'Accept':'application/vnd.github+json','User-Agent':'CreatePortal-A7','Authorization':'Bearer '+token,'Content-Type':'application/json'}
    req=urllib.request.Request(url,data=body,headers=headers,method='PUT')
    with urllib.request.urlopen(req,timeout=15) as resp:
        raw=resp.read(4096)
    return json.loads(raw)

def merge_due(conn,token_file,read_token_file=None,fetch_json=None,fetch_diff=None,merge=None,now=None,max_tasks=5):
    """One-at-a-time guarded merge. Rechecks PR, SHA, green verdict and kill switch.

    No merge token => no side effects. A failure cancels that attempt, never retries blind.
    """
    now=time.time() if now is None else now
    try:token=read_token(token_file)
    except (OSError,ValueError):return 0
    if not token:return 0
    count=0
    for job in conn.execute('SELECT * FROM task_auto_merge WHERE cancelled=0 AND due_at<=? ORDER BY due_at LIMIT ?',(now,max_tasks)).fetchall():
        slug,pid=job['project_slug'],job['pkg_id']
        cfg=conn.execute('SELECT * FROM project_a7_settings WHERE project_slug=?',(slug,)).fetchone()
        project=conn.execute('SELECT * FROM projects WHERE slug=?',(slug,)).fetchone()
        link=conn.execute('SELECT * FROM pr_links WHERE project_slug=? AND pkg_id=? AND pr_number=?',(slug,pid,job['pr_number'])).fetchone()
        conn.execute('UPDATE task_auto_merge SET cancelled=1 WHERE project_slug=? AND pkg_id=?',(slug,pid))
        if not cfg or not cfg['auto_merge'] or cfg['kill_switch'] or not project or not link or link['state']!='open' or link['ci_state']!='success' or not re.fullmatch(r'[0-9a-f]{40}',link['sha']):continue
        if not REPO.fullmatch(project['repo']):continue
        try:
            # GitHub's live head must match the reviewed SHA; stale PR/CI => no merge.
            getter=fetch_json or github_json
            root=f'https://api.github.com/repos/{project["repo"]}/pulls/{link["pr_number"]}'
            live=getter(root,read_token(read_token_file))
            if live.get('state')!='open' or live.get('draft') or live.get('head',{}).get('sha')!=link['sha'] or live.get('base',{}).get('ref')!=project['branch'] or live.get('mergeable') is not True:continue
            from portal.backup.sync import complete_checks
            if not complete_checks(project['repo'],link['sha'],read_token(read_token_file),fetch=lambda u,t,e=None:(getter(u,t),None)):continue
            v=evaluate(conn,slug,pid,project,read_token_file,fetch_json,fetch_diff,now)
            if not engine.auto_merge_allowed(v):continue
            merged=(merge or merge_request)(root+'/merge',token,link['sha'])
            if not isinstance(merged,dict) or merged.get('merged') is not True:continue
            conn.execute("UPDATE task_state SET status='accepted',merged=1,accepted_at=?,sha=? WHERE project_slug=? AND pkg_id=? AND status='submitted'",(now,link['sha'],slug,pid))
            conn.execute("UPDATE pr_links SET state='merged' WHERE project_slug=? AND pr_number=?",(slug,link['pr_number']))
            pkg=pkg_of(plan_of(project),pid)
            if pkg:record_success(conn,slug,pkg,plan_of(project))
            conn.execute('INSERT INTO events(project_slug,pkg_id,ts,kind,source,payload) VALUES(?,?,?,?,?,?)',(slug,pid,now,'task.auto_merge','a7','{}'))
            accepted={r['pkg_id'] for r in conn.execute("SELECT pkg_id FROM task_state WHERE project_slug=? AND status='accepted'",(slug,))}
            for next_pkg in plan_of(project).get('packages',[]):
                if next_pkg['id']!=pid and pid in next_pkg.get('depends_on',[]) and all(d in accepted for d in next_pkg['depends_on']):
                    conn.execute('INSERT INTO events(project_slug,pkg_id,ts,kind,source,payload) VALUES(?,?,?,?,?,?)',(slug,next_pkg['id'],now,'task.ready','a7','{}'))
            from portal import db
            db.audit(conn,'task.auto_merge',{'slug':slug,'id':pid})
            count+=1
        except (ValueError,OSError,TypeError,KeyError,UnicodeError):
            continue
    return count

def skeleton_for(project):
    from portal import bootstrap
    name,repo=project['name'],project['repo']
    files=bootstrap.files_for(name,repo,project['description'])
    kind=project['project_type']
    plan=project_types.starter_plan(kind,name,repo)
    path=project['plan_path']
    if path!='docs/work_plan.json':files.pop('docs/work_plan.json',None)
    files[path]=json.dumps(plan,ensure_ascii=False,indent=1)+'\n'
    files['docs/gdd/01_OVERVIEW.md']=project_types.gdd_outline(name)
    # Never modify the immutable templates; adapt the generated skeleton only.
    return files
