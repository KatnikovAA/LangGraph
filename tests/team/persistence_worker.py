import json
import sys
import threading
import time
from pathlib import Path
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from research_assistant.team.graph import build_team_graph
from research_assistant.team.demo import team_analyst,team_expert,team_synthesis,team_search,team_report

root=Path(sys.argv[1]);phase=sys.argv[2];root.mkdir(parents=True,exist_ok=True)
config={'configurable':{'thread_id':'persistent-team'},'max_concurrency':2}
lock=threading.Lock()
def log(kind,role):
    with lock:
        with (root/'calls.jsonl').open('a',encoding='utf-8') as handle:handle.write(json.dumps([kind,role])+'\n')
def analyst(*args,focus=''):
    log('analyst',args[2]);return team_analyst(*args,focus=focus)
def expert(*args):
    text=args[0]['text'];risk='Риски' in text
    log('expert','B' if risk else 'A')
    if phase=='first' and risk and 'в ответе' in text:
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            checkpoint=saver.get_tuple(config)
            if checkpoint and any(channel=='worker_results' and any(r['analyst_id']=='A' for r in value)
                for _,channel,value in checkpoint.pending_writes):
                raise ValueError('controlled B failure after durable A')
            time.sleep(.01)
        raise RuntimeError('A pending write not observed')
    return team_expert(*args)
def summary(*args):
    log('synthesis',args[1][0]['question']['text']);return team_synthesis(*args)
def search(query):
    log('search',query);return team_search(query)
def report(*args):
    log('report','parent');return team_report(*args)

with SqliteSaver.from_conn_string(str(root/'state.sqlite')) as saver:
    graph=build_team_graph(analyst=analyst,expert=expert,summarizer=summary,search_function=search,
        team_summarizer=report,checkpointer=saver,output_dir=str(root))
    if phase=='first':
        graph.invoke({'topic':'Persistence'},config)
        try:graph.invoke(Command(resume={'action':'approve'}),config)
        except ValueError:pass
        snapshot=graph.get_state(config,subgraphs=True)
        assert len(snapshot.values.get('worker_results',[]))==1,snapshot.values.keys()
        assert not list(root.glob('report-*.md'))
        (root/'first.json').write_text(json.dumps(snapshot.values,ensure_ascii=False),encoding='utf-8')
    else:
        result=graph.invoke(None,config)
        assert result['status']=='completed'
        (root/'final.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
