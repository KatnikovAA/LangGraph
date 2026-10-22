'use strict';
// UI projection only: no model calls, no raw State, no generated source URLs.
window.InterviewUI = (() => {
  const labels = {prepare_interview:'Подготовка интервью',ask_question:'Вопрос аналитика',search_sources:'Поиск источников',answer_question:'Ответ эксперта',summarize_interview:'Итог интервью',save_report:'Сохранение отчёта'};
  const steps = [['prepare_interview',0], ...[1,2].flatMap(r=>['ask_question','search_sources','answer_question'].map(n=>[n,r])), ['summarize_interview',2],['save_report',2]];
  let events = new Map(), current = null, disconnected = false;
  const el = (tag, value, cls) => {const node=document.createElement(tag);node.textContent=value;if(cls)node.className=cls;return node;};
  function reset(){events.clear();current=null;disconnected=false;document.getElementById('interview-panel').hidden=true;}
  function acceptProgress(event){
    if(!labels[event.node])return;
    disconnected=false;
    const before=events.get(event.execution_id);
    events.set(event.execution_id,{...before,...event,started_at:event.status==='running'?event.timestamp:before?.started_at});
    drawProgress();
  }
  function drawProgress(){
    const list=document.getElementById('interview-progress');list.replaceChildren();
    for(const [name,round] of steps){
      const matches=[...events.values()].filter(e=>e.node===name&&e.round===round);
      const record=matches.at(-1);
      let status=record?.status||'pending';
      const pending=current?.next?.[0]===name && (!['ask_question','search_sources','answer_question'].includes(name)||round===(current?.interview?.round||0)+(name==='ask_question'?1:0));
      if(pending&&current?.runStatus==='running'&&!record)status='running';
      if(current?.error&&pending)status='error';
      if(status==='running'&&(disconnected||current?.runStatus==='stopped'))status='disconnected';
      const item=el('li','',`interview-step ${status}`);
      const states={pending:'Ожидает',running:'Выполняется',done:'Завершено',error:'Ошибка',disconnected:'Связь прервана — обновите состояние'};
      item.append(el('strong',labels[name]+(round&&['ask_question','search_sources','answer_question'].includes(name)?` · раунд ${round}`:'')),el('small',name),el('span',states[status]));
      if(record?.started_at&&record?.timestamp&&status==='done'){
        const seconds=Math.max(0,(Date.parse(record.timestamp)-Date.parse(record.started_at))/1000);
        item.append(el('small',`${seconds.toFixed(1)} с`));
      }
      if(status==='running')item.setAttribute('aria-current','step');
      list.append(item);
    }
  }
  function citation(parent, sid, sources){
    const source=sources[Number(sid.slice(1))-1];
    if(!source)return;
    const a=el('a',sid);try{const u=new URL(source.url);if(!['http:','https:'].includes(u.protocol))return;a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';parent.append(a);}catch{}
  }
  function render(state,runStatus){
    const panel=document.getElementById('interview-panel');panel.hidden=!state?.interview;
    if(!state?.interview)return;
    current={...state,runStatus};
    for(const event of state.interview.progress||[])events.set(event.execution_id,{...events.get(event.execution_id),...event});
    const transcript=document.getElementById('interview-transcript');transcript.replaceChildren();
    const questions=state.interview.questions||[],answers=state.interview.answers||[];
    if(!questions.length)transcript.append(el('p','Подготавливаем интервью. Вопросы и ответы появятся здесь.','muted'));
    questions.forEach((q,i)=>{
      const card=el('section','', 'interview-round');card.append(el('h3',`Раунд ${i+1}`),el('strong','Аналитик · Технический аналитик'),el('p',q.text),el('strong','Эксперт'));
      const answer=answers[i];
      card.append(el('p',answer?answer.text:'Ответ ещё не получен. Это не завершённая реплика.','interview-answer'));
      if(answer){const refs=el('div','Источники: ','interview-refs');if(!answer.source_ids.length)refs.append(el('span','Нет найденных материалов'));for(const sid of answer.source_ids)citation(refs,sid,state.sources);card.append(refs);}
      transcript.append(card);
    });
    const sources=document.getElementById('interview-sources');sources.replaceChildren();
    (state.sources||[]).forEach((source,i)=>{
      const details=document.createElement('details');details.append(el('summary',`S${i+1} · ${source.title}`));
      const link=el('a',source.url);try{const u=new URL(source.url);if(['http:','https:'].includes(u.protocol)){link.href=u.href;link.target='_blank';link.rel='noopener noreferrer';}}catch{}
      details.append(link,el('p',source.snippet));sources.append(details);
    });
    if(!state.sources?.length)sources.append(el('p','Источников пока нет. Ответы не будут опираться на вымышленные материалы.','muted'));
    document.getElementById('interview-resume').hidden=!state.next?.length||runStatus==='running';
    document.getElementById('interview-limitations').textContent=(state.interview.limitations||[]).join(' ');
    drawProgress();
  }
  function connectionLost(){disconnected=true;drawProgress();}
  return {reset,render,acceptProgress,connectionLost};
})();
