from copy import deepcopy
from research_assistant.interview.sources import merge_sources, validate_source_ids
from research_assistant.team.schemas import WorkerResult


def remap_source_ids(ids: list[str], mapping: dict[str,str]) -> list[str]:
    return [mapping[sid] for sid in validate_source_ids(ids,list(mapping))]


def collect_team_sources(results: list[dict]) -> dict:
    ordered=sorted([WorkerResult.model_validate(r).model_dump(mode='json') for r in results],key=lambda r:r['analyst_id'])
    if [r['analyst_id'] for r in ordered]!=['A','B']:
        raise ValueError('Общий отчёт требует оба интервью A и B.')
    registry=[];mapping={};origins={};findings=[]
    for index,result in enumerate(ordered):
        analyst_id=result['analyst_id'];mapping[analyst_id]={}
        for number,source in enumerate(result['sources'],1):
            registry,ids=merge_sources(registry,[source],index+1)
            local_id=f'S{number}';global_id=ids[0]
            mapping[analyst_id][local_id]=global_id
            origins.setdefault(global_id,[]).append({'analyst_id':analyst_id,'local_source_id':local_id})
        draft=deepcopy(result['report_draft'])
        for section in draft['sections']:
            section['source_ids']=remap_source_ids(section['source_ids'],mapping[analyst_id])
        findings.append({'analyst_id':analyst_id,'role':result['role'],'report_draft':draft,'limitations':result['limitations']})
    return dict(sources=registry,source_mapping=mapping,source_origins=origins,findings=findings)
