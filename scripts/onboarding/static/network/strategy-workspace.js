import {defaultDate, defaultOwner, escapeHtml as esc, queryUrl, realNetwork} from './client.js';
import {mountStrategyMap} from './strategy-map.js';

const params=new URLSearchParams(location.search);
const context={focus:params.get('focus')||defaultOwner(),as_of:params.get('as_of')||defaultDate(),mode:params.get('mode')==='history'?'history':'current'};
const $=selector=>document.querySelector(selector), form=$('#strategy-form'), input=$('#strategy-goal'), start=$('#strategy-start'), stop=$('#strategy-cancel');
const status=$('#strategy-status'), reconnect=$('#strategy-reconnect'), mapHost=$('#strategy-map'), analysis=$('#strategy-analysis');
const emptyMap=mapHost.innerHTML, emptyAnalysis=analysis.innerHTML;
const terminalTypes=new Set(['completed','failed','cancelled','invalidated']);
let runId='',lastSeq=0,stream=null,terminal=false,active=false,map=null,hasPartial=false,generation=0,historyTurns=[],historyRunIds=[];
let tasks=new Map(),requirementNames=new Map(),entityNames=new Map();

function renderContext(){
  $('#strategy-context').textContent=`${context.mode==='history'?'Relationship history':'Current relationships'} · Known by ${context.as_of.slice(0,10)} · ${realNetwork()?'Source-backed records':'Synthetic evidence'}`;
  $('#return-link').href=queryUrl('/network',context);
}
function restoreRequest(request){
  if(!request)return;
  if(typeof request.question==='string')input.value=request.question;
  for(const key of ['focus','as_of','mode'])if(typeof request[key]==='string')context[key]=request[key];
  renderContext();
}
renderContext();
function notice(text,state=''){status.textContent=text;status.dataset.state=state;}
function controls(running){active=running;start.disabled=running;stop.hidden=!running||!runId||terminal;stop.disabled=false;input.readOnly=running;start.textContent=running?'Analyzing…':runId?'Run again':'Start analysis';}
function closeStream(){stream?.close();stream=null;}
function clearHistory(){historyTurns=[];historyRunIds=[];}
function clearResults(){map?.destroy();map=null;mapHost.innerHTML=emptyMap;analysis.innerHTML=emptyAnalysis;hasPartial=false;entityNames.clear();$('#strategy-snapshot').textContent='';$('#strategy-evaluation').replaceChildren();$('#strategy-evaluation').hidden=true;}
function reset(){closeStream();lastSeq=0;terminal=false;tasks=new Map();requirementNames.clear();$('#strategy-tasks').replaceChildren();$('#strategy-plan').hidden=true;clearResults();reconnect.hidden=true;}
function renderTasks(){
  const labels={pending:'Waiting',running:'Searching',completed:'Complete',failed:'Unavailable',cancelled:'Stopped'};
  $('#strategy-tasks').innerHTML=[...tasks.values()].map(t=>`<li data-task="${esc(t.id)}" data-state="${esc(t.state)}"><span>${esc(t.label)}</span><small>${esc(labels[t.state]||t.state)}</small></li>`).join('');
}
function renderPlan(data){
  for(const r of data.requirements||[])requirementNames.set(r.id,r.label);
  $('#strategy-plan').hidden=false;$('#strategy-intent').textContent=data.intent||'';
  $('#strategy-requirements').innerHTML=(data.requirements||[]).map(r=>`<span class="strategy-requirement"><small>${r.origin==='suggested'?'Suggested':r.priority==='prefer'?'Preferred':r.priority==='exclude'?'Exclude':'Requested'}</small>${esc(r.label)}</span>`).join('');
  for(const t of data.tasks||[])tasks.set(t.id,{...t,state:tasks.get(t.id)?.state||'pending'});
  renderTasks();
}
function renderPartial(data){
  for(const n of data.entities||data.strategy_graph?.nodes||[])entityNames.set(n.id,n.name);
  for(const task of data.retrieval?.tasks||[]){
    const existing=tasks.get(task.task_id);
    const description=(task.requirement_ids||[]).map(id=>requirementNames.get(id)||id).join(', ')||(task.terms||[]).slice(0,4).join(', ')||entityNames.get(task.entity_id)||'context';
    tasks.set(task.task_id,{...existing,id:task.task_id,label:existing?.label&&existing.label!=='Evidence search'?existing.label:`Check ${description}`,state:task.status});
  }
  renderTasks();
  if(data.strategy_graph){
    if(map)map.update(data.strategy_graph);else map=mountStrategyMap(mapHost,data.strategy_graph,context);
    hasPartial=true;
  }
  if(data.version!==undefined)$('#strategy-snapshot').textContent=`Snapshot ${data.version}`;
}
function coverageLabel(row){
  const labels={matching_evidence:'Matching records found; capability still needs validation',searched_no_match:'No match in searched records',budget_omitted:'Retrieval budget reached; coverage remains unknown',not_searched:'Not fully searched',search_incomplete:'Search incomplete; remaining coverage is unknown'};
  const label=labels[row.status]||row.status;
  return row.search_status==='incomplete'&&row.status!=='search_incomplete'?`${label}. Search incomplete; remaining coverage is unknown`:label;
}
function validationState(data){
  const summary=data.strategy_validation||data.validation_summary||{};
  return {partial:summary.partial===true,retained:summary.previous_evaluation_retained===true||data.previous_evaluation_retained===true};
}
function validationNotice(data){
  const value=validationState(data);
  if(!value.partial&&!value.retained)return '';
  const omitted=value.partial?'Some model suggestions were omitted because they could not be validated. The options shown remain provisional.':'';
  const retained=value.retained?'Earlier provisional options were retained after their source references were rechecked. They are not a newly completed assessment.':'';
  return `<p class="strategy-validation-notice" role="note">${esc([omitted,retained].filter(Boolean).join(' '))}</p>`;
}
function renderAnswer(data){
  renderPartial(data);
  if(data.strategy_evaluation)renderEvaluation({...data.strategy_evaluation,validation_summary:data.strategy_validation||data.strategy_evaluation.validation_summary,previous_evaluation_retained:data.previous_evaluation_retained});
  const names=new Map((data.entities||[]).map(n=>[n.id,n.name])),sources=new Map((data.evidence||[]).map(s=>[s.id,s]));
  const entityLink=id=>`<a href="${esc(queryUrl('/network',{...context,focus:id,expand:id,scopes:'direct,explicit,project,organization'}))}">${esc(names.get(id)||id)}</a>`;
  analysis.innerHTML=`<span class="agent-advisory">Strategy suggestion · validate before acting</span>${validationNotice(data)}<p class="agent-summary">${esc(data.summary||'')}</p>
    ${(data.findings||[]).length?'<h3>What the evidence supports</h3>':''}${(data.findings||[]).map(f=>`<section class="agent-finding"><p>${esc(f.text)}</p><div class="agent-entity-links">${(f.entity_ids||[]).map(entityLink).join('')}</div><details><summary>${(f.evidence_ids||[]).length} source records</summary>${(f.evidence_ids||[]).map(id=>{const s=sources.get(id);return s?`<p><a href="${esc(queryUrl('/network/evidence/'+encodeURIComponent(id)+'.json',{as_of:context.as_of,version:data.version}))}" target="_blank" rel="noopener">${esc(s.channel)} · ${esc(s.at?.slice(0,10))}</a></p><blockquote>${esc(s.text)}</blockquote>`:'<p>Source outside this answer.</p>';}).join('')}</details></section>`).join('')}
    ${(data.gaps||[]).length?`<h3>What is not established yet</h3><ul>${data.gaps.map(g=>`<li>${esc(g)}</li>`).join('')}</ul>`:''}
    ${(data.next_steps||[]).length?`<h3>Suggested next moves</h3><ol>${data.next_steps.map(s=>`<li>${esc(s)}</li>`).join('')}</ol>`:''}
    ${data.clarification?`<p>${esc(data.clarification)}</p>`:''}
    ${data.retrieval?`<details class="agent-trace"><summary>Search coverage</summary><p>${esc(data.retrieval.scope?.scanned_people??0)} contacts searched · ${esc(data.retrieval.budget?.selected_records??0)} evidence records included</p><ul class="agent-coverage">${(data.retrieval.coverage||[]).map(c=>`<li><strong>${esc(c.label)}</strong>: ${esc(coverageLabel(c))}</li>`).join('')}</ul></details>`:''}`;
  historyTurns.push({question:input.value,answer:[data.summary,...(data.next_steps||[])].join('\n').slice(0,1500)});historyTurns=historyTurns.slice(-4);historyRunIds.push(runId);historyRunIds=historyRunIds.slice(-4);
}
function renderEvaluation(data){
  const section=$('#strategy-evaluation');section.hidden=false;
  const assessmentById=new Map((data.assessments||[]).map(a=>[a.id,a]));
  const requirement=id=>esc(requirementNames.get(id)||id);
  const person=id=>id?`<a href="${esc(queryUrl('/network',{...context,focus:id}))}">${esc(entityNames.get(id)||id)}</a>`:'';
  const evidence=rows=>(rows||[]).length?`<details><summary>Inspect cited evidence</summary>${rows.map(r=>`<a href="${esc(queryUrl('/network/evidence/'+encodeURIComponent(r.evidence_id)+'.json',{as_of:context.as_of}))}" target="_blank" rel="noopener">Open source</a><blockquote>${esc(r.quote)}</blockquote>`).join('')}</details>`:'';
  const state=a=>a.state==='supported'?(a.scope==='historical_observation'?'Historical evidence':'Reported condition'):a.state==='obstacle'?'Potential constraint conflict':'Insufficient evidence';
  const comparisons={requirement_coverage:'Requirement coverage',complementarity:'Complementary contributions',evidence_support:'Evidence support',contact_paths:'Contact paths',unresolved_dependencies:'Unresolved dependencies'};
  section.innerHTML=`<div class="strategy-section-heading"><h2>Options and what they depend on</h2><span>${data.round?`Assessment ${esc(data.round)}`:'Assessment'}</span></div><p class="strategy-caption">These are conditional options. Cited observations do not establish present availability or willingness. ${esc(data.validation_note||'Source references are checked; the interpretation still needs your judgment.')}</p>
    ${validationNotice(data)}
    <div class="strategy-assessments" role="region" aria-label="Requirement coverage" tabindex="0"><table><caption>Evidence for each requirement and candidate</caption><thead><tr><th scope="col">Requirement / candidate</th><th scope="col">Evidence assessment</th><th scope="col">What still needs checking</th></tr></thead><tbody>${(data.assessments||[]).map(a=>`<tr data-assessment="${esc(a.id)}"><th scope="row">${requirement(a.requirement_id)}<small>${person(a.subject_id)}</small></th><td><span class="assessment-state" data-state="${esc(a.state)}">${esc(state(a))}</span><p>${esc(a.statement)}</p>${evidence(a.evidence)}</td><td>${esc(a.limitation)}${a.hard_constraint_quote?`<p>Requested constraint: “${esc(a.hard_constraint_quote)}”</p>`:''}</td></tr>`).join('')}</tbody></table></div>
    <div class="strategy-options">${(data.alternatives||[]).map(option=>{
      const actions=new Map((option.actions||[]).map(a=>[a.id,a.text]));
      return `<article data-alternative="${esc(option.id)}" class="strategy-option"><div class="strategy-option-heading"><h3>${esc(option.label)}</h3><span>${option.status==='eliminated'?'Constraint conflict to review':'Conditional option'}</span></div><ul class="strategy-assignments">${(option.assignments||[]).map(a=>`<li>${requirement(a.requirement_id)}: ${person(a.subject_id)} <small>${esc(assessmentById.has(a.assessment_id)?state(assessmentById.get(a.assessment_id)):'Needs checking')}</small></li>`).join('')}</ul><dl>${Object.entries(comparisons).filter(([key])=>option.comparison?.[key]).map(([key,label])=>`<dt>${esc(label)}</dt><dd>${esc(option.comparison[key])}</dd>`).join('')}</dl>${(option.actions||[]).length?`<h4>Proposed next steps</h4><ol>${option.actions.map(a=>`<li><p>${esc(a.text)}</p>${a.depends_on?.length?`<small class="strategy-dependency">After: ${a.depends_on.map(id=>esc(actions.get(id)||id)).join('; ')}</small>`:'<small class="strategy-dependency">No earlier action specified</small>'}${evidence(a.evidence)}</li>`).join('')}</ol>`:''}${(option.obstacle_assessment_ids||[]).map(id=>`<p class="strategy-constraint">Constraint to review: ${esc(assessmentById.get(id)?.statement||'Inspect cited assessment')}</p>`).join('')}</article>`;
    }).join('')}</div>
    ${(data.pending_constraints||[]).length?`<section class="strategy-open-questions"><h3>Questions to resolve</h3><ul>${data.pending_constraints.map(c=>`<li><span>${c.origin==='missing_user_detail'?'From you':'Evidence gap'}</span>${esc(c.question)}</li>`).join('')}</ul></section>`:''}
    ${(data.next_searches||[]).length?`<section class="strategy-next-searches"><h3>Next evidence checks</h3><ul>${data.next_searches.map(s=>`<li><strong>${requirement(s.requirement_id)}</strong>: ${esc(s.reason)}</li>`).join('')}</ul></section>`:''}`;
  section.querySelector('.strategy-assessments').hidden=!(data.assessments||[]).length;
}
function applyEvent(event){
  if(!event||!Number.isInteger(event.seq)||event.seq<=lastSeq)return;
  if(terminal&&event.type!=='invalidated')return;
  lastSeq=event.seq;const data=event.data||{};
  if(event.type==='started'){restoreRequest(data.request);notice('Understanding your goal…');}
  if(event.type==='plan'){renderPlan(data);notice('Finding candidate evidence. Independent searches can finish separately.');}
  if(event.type.startsWith('task_')){
    const task=tasks.get(data.task_id)||{id:data.task_id,label:data.label||'Evidence search'};
    task.state=({task_started:'running',task_completed:'completed',task_failed:'failed'})[event.type]||'pending';tasks.set(task.id,task);renderTasks();
  }
  if(event.type==='partial'){renderPartial(data);notice('Candidate evidence is ready to explore. Analysis continues.');}
  if(event.type==='assessment'){renderEvaluation(data);notice(validationState(data).partial?'Some model suggestions were omitted. Provisional options are shown while evidence checks continue.':'Conditional options are ready. Checking the remaining evidence gaps.');}
  if(event.type==='synthesizing')notice('Building the assessment from checked evidence. You can explore the map now.');
  if(event.type==='completed'){
    renderAnswer(data);
    const validation=validationState(data);
    notice(validation.partial?'Analysis finished with omitted suggestions. The assessment remains incomplete.':validation.retained?'Analysis finished with earlier provisional options rechecked and retained. The assessment remains incomplete.':'Analysis complete. Review the evidence and remaining assumptions.',validation.partial||validation.retained?'partial':'completed');
  }
  if(event.type==='failed')notice(`${data.message||'Analysis could not finish.'}${hasPartial?' Partial results retained; unfinished work remains unknown.':' You can try again.'}`,'failed');
  if(event.type==='cancelled')notice(`Stopped.${hasPartial?' Partial results retained.':''} Unfinished searches remain unknown.`,'cancelled');
  if(event.type==='invalidated'){clearResults();clearHistory();notice('These results are no longer valid because source evidence changed or could not be checked. Run again to refresh.','invalidated');}
  if(terminalTypes.has(event.type)){
    terminal=true;controls(false);closeStream();reconnect.hidden=true;
    for(const task of tasks.values())if(['pending','running'].includes(task.state))task.state=event.type==='cancelled'?'cancelled':'failed';renderTasks();
    if(['failed','cancelled'].includes(event.type)&&!analysis.querySelector('.agent-summary'))analysis.innerHTML='<p class="strategy-empty-copy">The final assessment is incomplete. You can inspect the available candidate evidence and conditional options. Unfinished searches remain unknown.</p>';
  }
}
async function jsonRequest(url,options={}){
  const response=await fetch(url,{cache:'no-store',...options});
  let data;try{data=await response.json();}catch{throw new Error('The local app returned an unavailable response. Try reconnecting.');}
  if(!response.ok)throw new Error(data.error||'The request could not complete. Try again.');return data;
}
function connect(){
  closeStream();if(terminal||!runId)return;
  const id=runId,ticket=generation;
  stream=new EventSource(`/network/strategy/runs/${encodeURIComponent(id)}/events?after=${lastSeq}`);
  stream.onmessage=e=>{
    if(ticket!==generation||id!==runId)return;
    try{applyEvent(JSON.parse(e.data));}catch{closeStream();notice('The update could not be read. Reconnect to retrieve checked results.');reconnect.hidden=false;}
  };
  stream.onerror=()=>{
    if(ticket!==generation||terminal)return;
    closeStream();notice('Connection interrupted. Displayed results may be out of date; reconnect to check them.');reconnect.hidden=false;
  };
}
async function restore(){
  reconnect.hidden=true;
  try{
    const snapshot=await jsonRequest(`/network/strategy/runs/${encodeURIComponent(runId)}`);
    restoreRequest(snapshot.request);
    for(const event of snapshot.events||[])applyEvent(event);
    if(!terminal){controls(true);connect();}
  }catch(error){
    clearResults();clearHistory();closeStream();controls(false);notice(error.message,'failed');reconnect.hidden=false;
  }
}
reconnect.onclick=restore;
form.onsubmit=async e=>{
  e.preventDefault();const question=input.value.trim();if(!question||active)return;
  controls(true);notice('Starting analysis…');
  try{
    if(historyTurns.length){
      try{
        const previous=await Promise.all([...new Set(historyRunIds)].map(id=>jsonRequest(`/network/strategy/runs/${encodeURIComponent(id)}`)));
        if(previous.some(s=>s.status==='invalidated'||(s.events||[]).some(e=>e.type==='invalidated')))throw new Error('invalidated');
      }catch{
        clearResults();clearHistory();
        throw new Error('Previous source context changed or could not be checked. Retained context was cleared. Review your goal and run again to start fresh.');
      }
    }
    const created=await jsonRequest('/network/strategy/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,...context,history:historyTurns})});
    generation++;reset();runId=created.run_id;controls(true);
    const next=new URL(location.href);next.searchParams.delete('draft');next.searchParams.set('run',runId);window.history.replaceState(null,'',next);connect();
  }catch(error){controls(false);notice(error instanceof TypeError?'Could not reach the local app. Your goal has been kept.':error.message,'failed');}
};
stop.onclick=async()=>{
  stop.disabled=true;
  try{await jsonRequest(`/network/strategy/runs/${encodeURIComponent(runId)}/cancel`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(!terminal)notice('Stopping further work. An in-flight request may take a moment to finish.');}
  catch(error){stop.disabled=false;notice(error.message,'failed');}
};
window.addEventListener('pagehide',closeStream);
fetch('/network/agent/status.json',{cache:'no-store'}).then(r=>r.json()).then(s=>{
  $('#strategy-provider').textContent=s.configured?`Uses Claude · ${s.remaining} questions left in this session. Start analysis when your goal is ready.`:'Claude is not configured. Configure the local app before starting analysis.';
}).catch(()=>{$('#strategy-provider').textContent='Could not check Claude availability. Starting analysis may be unavailable.';});
if(params.get('run')){runId=params.get('run');controls(true);notice('Checking saved results…');restore();}
else if(params.get('draft')){
  start.disabled=true;
  jsonRequest(`/network/strategy/drafts/${encodeURIComponent(params.get('draft'))}`).then(d=>{input.value=d.question||'';input.focus();}).catch(error=>notice(error.message,'failed')).finally(()=>{start.disabled=false;});
}
