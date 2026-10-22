from research_assistant.team.schemas import AnalystRole, WorkerResult


def build_worker(core):
    def interview_worker(state, config):
        role=AnalystRole.model_validate(state['role']).model_dump(mode='json')
        result=core.invoke({'topic':state['topic'],'clarification':state.get('clarification',''),
            'analyst_id':role['analyst_id'],'analyst_role':role['name'],'focus':role['focus']},config)
        output={k:result[k] for k in ('transcript','questions','answers','search_queries','sources','report_draft','limitations','progress')}
        validated=WorkerResult.model_validate({**output,'analyst_id':role['analyst_id'],'role':role,'focus':role['focus']})
        return {'worker_results':[validated.model_dump(mode='json')]}
    return interview_worker
