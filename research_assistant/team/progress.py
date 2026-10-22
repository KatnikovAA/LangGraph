from research_assistant.interview.progress import project_progress


def project_team_progress(data: dict,run_id: str) -> dict|None:
    if not isinstance(data,dict) or data.get('analyst_id') not in ('A','B','parent'):return None
    event=project_progress(data,run_id)
    return {**event,'analyst_id':data['analyst_id']} if event else None


def team_public_state(snapshot: dict) -> dict:
    values=snapshot.get('values') or {}
    workers={r['analyst_id']:{'analyst_id':r['analyst_id'],'role':r['name'],'focus':r['focus'],
        'status':'pending','round':0,'next':[],'error':False,'questions':[],'answers':[],
        'transcript':[],'sources':[],'progress':[],'limitations':[]} for r in values.get('roles',[])}
    for result in values.get('worker_results',[]):
        key=result['analyst_id']
        workers[key]={k:result[k] for k in ('analyst_id','focus','questions','answers','transcript','sources','progress','limitations')}
        workers[key].update(role=result['role']['name'],round=2,status='completed',next=[],error=False)
    def visit(data,inherited_error=False):
        if not isinstance(data,dict):return
        state=data.get('values') or {}
        key=state.get('analyst_id')
        error=inherited_error or any(t.get('error') for t in data.get('tasks',[]))
        if key in ('A','B') and workers.get(key,{}).get('status')!='completed':
            workers[key]={k:state.get(k,[]) for k in ('questions','answers','transcript','sources','progress','limitations')}
            workers[key].update(analyst_id=key,role=state.get('analyst_role',''),focus=state.get('focus',''),
                round=state.get('round',0),status='error' if error else state.get('status','pending'),
                next=data.get('next',[]),error=bool(error))
        for task in data.get('tasks',[]):visit(task.get('state'),bool(task.get('error')))
    visit(snapshot)
    return {'roles':values.get('roles',[]),'review_decision':values.get('review_decision'),
        'workers':workers,'progress':values.get('progress',[]),'source_mapping':values.get('source_mapping',{}),
        'source_origins':values.get('source_origins',{}),'status':values.get('status','new')}
