'use strict';
window.TeamUI=(()=>{
  const names={prepare_interview:'Подготовка',ask_question:'Вопрос аналитика',search_sources:'Поиск',answer_question:'Ответ эксперта',summarize_interview:'Выводы'};
  const steps=[['prepare_interview',0],...[1,2].flatMap(r=>['ask_question','search_sources','answer_question'].map(n=>[n,r])),['summarize_interview',2]];
  const statuses={pending:'Ожидает',running:'Выполняется',done:'Завершено',error:'Ошибка',disconnected:'Связь прервана'};
  let current=null,events=new Map(),lost=false,reviewKey=null;
  const node=(tag,value,cls)=>{const e=document.createElement(tag);e.textContent=value;if(cls)e.className=cls;return e;};
  function link(title,url){const e=node('a',title);try{const u=new URL(url);if(['http:','https:'].includes(u.protocol)){e.href=u.href;e.target='_blank';e.rel='noopener noreferrer';}}catch{}return e;}
  function reset(){current=null;events.clear();lost=false;reviewKey=null;document.getElementById('team-panel').hidden=true;}
  function beginRun(){events.clear();lost=false;}
  function readDecision(action){
    if(action==='cancel')return {action};
    const roles=['A','B'].map(id=>({analyst_id:id,name:document.getElementById('team-name-'+id).value.trim(),focus:document.getElementById('team-focus-'+id).value.trim()}));
    for(const role of roles)if(!role.name||!role.focus||role.name.length>120||role.focus.length>1000)throw Error('Заполните название (до 120) и фокус (до 1000 символов) обеих ролей.');
    return JSON.stringify(roles)===JSON.stringify(current.team.roles)?{action:'approve'}:{action:'edit',roles};
  }
  function render(state,runStatus){
    const panel=document.getElementById('team-panel');panel.hidden=!state?.team;
    if(!state?.team)return;
    current={...state,runStatus};
    const review=state.next?.includes('review_analysts');document.getElementById('team-review').hidden=!review;
    if(review&&reviewKey!==state.checkpoint_id){
      for(const role of state.team.roles){document.getElementById('team-name-'+role.analyst_id).value=role.name;document.getElementById('team-focus-'+role.analyst_id).value=role.focus;}
      reviewKey=state.checkpoint_id;
    }
    const labels={roles_ready:'Проверьте роли — модель и поиск ещё не запускались.',approved:'Ожидаем завершения обоих интервью.',team_report_ready:'Формируем общий Report.',report_ready:'Сохраняем общий Report.',completed:'Общий Report готов.',cancelled:'Команда отменена; интервью не запускались.'};
    document.getElementById('team-status').textContent=state.error?'Работа остановилась с ошибкой. Успешные шаги сохранены; доступен Resume.':labels[state.status]||state.status;
    document.getElementById('team-resume').hidden=review||!state.next?.length||runStatus==='running';
    for(const worker of Object.values(state.team.workers||{}))for(const event of worker.progress||[])events.set(event.execution_id,{...events.get(event.execution_id),...event,analyst_id:worker.analyst_id});
    draw();
  }
  function acceptProgress(event){
    lost=false;
    const previous=events.get(event.execution_id);
    events.set(event.execution_id,{...previous,...event,started_at:event.status==='running'?event.timestamp:previous?.started_at});
    if(event.analyst_id==='parent')document.getElementById('team-status').textContent=event.label;
    draw();
  }
  function draw(){
    if(!current)return;
    const container=document.getElementById('team-workers');container.replaceChildren();
    for(const role of current.team.roles||[]){
      const id=role.analyst_id,worker=current.team.workers[id]||{};
      const panel=node('section','', 'team-worker');panel.dataset.analystId=id;
      panel.setAttribute('aria-label','Аналитик '+id);panel.append(node('h3',`${id} · ${role.name}`),node('p',role.focus,'muted'));
      const progress=node('ol','', 'team-steps');progress.setAttribute('aria-live','polite');
      for(const [name,round] of steps){
        const record=[...events.values()].filter(e=>e.analyst_id===id&&e.node===name&&e.round===round).at(-1);
        let status=record?.status||'pending';
        const pending=worker.next?.[0]===name&&round===(name==='ask_question'?(worker.answers?.length||0)+1:worker.round||0);
        if(worker.status==='completed')status='done';
        else if(pending&&worker.error&&current.runStatus!=='running')status='error';
        else if(pending&&current.runStatus==='running'&&!record)status='running';
        if(status==='running'&&(lost||current.runStatus!=='running'))status='disconnected';
        const item=node('li','',status);item.append(node('strong',names[name]+(round?` · ${round}`:'')),node('small',name),node('span',statuses[status]));
        if(status==='running')item.setAttribute('aria-current','step');
        if(status==='done'&&record?.started_at)item.append(node('small',`${Math.max(0,(Date.parse(record.timestamp)-Date.parse(record.started_at))/1000).toFixed(1)} с`));
        progress.append(item);
      }
      panel.append(progress);
      const transcript=document.createElement('details');transcript.open=true;transcript.append(node('summary','Полный Transcript · '+id));
      if(!worker.questions?.length)transcript.append(node('p','Вопросы появятся после утверждения ролей.','muted'));
      (worker.questions||[]).forEach((question,index)=>{
        const card=node('div','', 'team-round'),answer=worker.answers?.[index];
        card.append(node('h4','Раунд '+(index+1)),node('strong','Аналитик '+id),node('p',question.text),node('strong','Эксперт'),node('p',answer?.text||'Ответ ещё не получен.'));
        if(answer){const refs=node('div',answer.source_ids.length?'Источники: ':'Нет найденных материалов','team-refs');for(const sid of answer.source_ids){const source=worker.sources?.[Number(sid.slice(1))-1];if(source)refs.append(link(sid,source.url));}card.append(refs);}
        transcript.append(card);
      });
      panel.append(transcript);
      for(const [index,source] of (worker.sources||[]).entries()){
        const detail=document.createElement('details');detail.append(node('summary',`${id}/S${index+1} · ${source.title}`),link(source.url,source.url),node('p',source.snippet));panel.append(detail);
      }
      if(worker.limitations?.length)panel.append(node('p',worker.limitations.join(' '),'team-warning'));
      container.append(panel);
    }
  }
  function connectionLost(){lost=true;draw();}
  return {reset,beginRun,render,acceptProgress,readDecision,connectionLost};
})();
