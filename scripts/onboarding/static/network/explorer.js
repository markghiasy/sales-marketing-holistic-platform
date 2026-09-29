import {openAssistant} from './assistant.js';
import {mountContext} from './context.js';
import {mountGraph} from './graph.js';
import {createNetworkClient,readQuery,queryUrl,escapeHtml as esc,initials,claimMarkup,bindEvidence,preserveFocus} from './client.js';

const query={...readQuery(),view:'explorer'};
const scopes={direct:'Direct interaction',explicit:'Collaboration or introduction',project:'Shared project or team',organization:'Shared organization or company'};
let snapshot,selectedId=query.focus,selectedClaim=new URLSearchParams(location.search).get('claim')||'',optionsReady=false;
const expanded=new Set();
let inspectorDismissed=false;
const inspector=document.getElementById('inspector'),status=document.getElementById('network-status');
const graph=mountGraph(document.getElementById('graph'),{onNodeSelect:id=>{inspectorDismissed=false;selectedId=id;selectedClaim='';renderInspector();},onEdgeSelect:id=>{inspectorDismissed=false;selectedClaim=id;renderInspector();}});
function setStatus(text,error=false){status.textContent=text;status.classList.toggle('error',error);}
function syncUrl(){
  const state={...query};
  if(selectedClaim)state.claim=selectedClaim;
  history.replaceState(null,'',queryUrl('/network',state));
  const link=document.getElementById('return-link');
  link.href=queryUrl('/inbox',{...state,focus:query.origin||query.focus});
  link.textContent=query.origin?'Return to conversation':'Back to inbox';
}
const client=createNetworkClient({query,onSnapshot(data,state){
  const restoreFocus=preserveFocus(document.body);
  snapshot=data;Object.assign(query,state);
  if(selectedClaim&&!data.edges.some(e=>e.id===selectedClaim))selectedClaim='';
  graph.setSnapshot(data);renderOptions();renderPeople();renderInspector();renderExpansion();restoreFocus();syncUrl();
  document.getElementById('snapshot-count').textContent=`${data.nodes.length} entities / ${data.edges.length} connections${data.truncated?' · '+data.omitted_counts.nodes+' more hidden':''}`;
  document.getElementById('graph-empty').hidden=!!data.ranked_contacts.length||!!query.expand;
  setStatus(`${data.data_source==='real'?'Local source · Last refresh '+(data.freshness?.last_success_at||'pending'):'Synthetic demo'} · Snapshot ${data.version} · ${data.truncated?'Bounded view; refine filters to explore further.':'All eligible connections in this view.'}${data.freshness?.error_code?' · Refresh delayed; showing last successful state.':''}`);
},onError:message=>setStatus(message,true)});

function updateQuery(patch){Object.assign(query,patch);syncUrl();client.setQuery(patch);}
function renderOptions(){
  if(optionsReady)return;
  for(const [key,items] of [['function',snapshot.options.functions.map(f=>({id:f,name:f}))],['organization',snapshot.options.organizations],['project',snapshot.options.projects]]){
    const select=document.querySelector(`[name="${key}"]`);
    select.insertAdjacentHTML('beforeend',items.map(i=>`<option value="${esc(i.id)}">${esc(i.name)}</option>`).join(''));select.value=query[key];
  }
  document.querySelector('[name=search]').value=query.search;
  document.getElementById('as-of').value=query.as_of.slice(0,10);
  document.getElementById('hypotheses').checked=String(query.include_pending)==='true';
  document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('active',b.dataset.mode===query.mode));optionsReady=true;
}
function scopeTags(scope){
  return `<span class="scope-tags">${(scope?.scopes||[]).map(key=>`<span data-scope="${esc(key)}">${esc(scopes[key]||key)}</span>`).join('')}</span>`;
}
function relationshipEvent(scope){return scope?.last_event_at?`Latest relationship event: ${scope.last_event_at.slice(0,10)}`:'No recorded relationship event';}
function renderPeople(){
  const lens=document.getElementById('entity-lens').value;
  if(lens!=='person'){
    document.querySelector('.panel-heading h2').textContent=lens==='project'?'Projects':'Organizations';
    const items=lens==='organization'?snapshot.options.organizations:snapshot.options.projects;
    document.getElementById('people-count').textContent=items.length;
    document.getElementById('ranking-caption').textContent=lens==='project'?'Team, responsibilities and follow-ups':'People, functions and shared context';
    document.getElementById('people').innerHTML=items.map(n=>`<button class="person-row ${selectedId===n.id?'selected':''}" data-context="${esc(n.id)}"><span class="person-avatar">${initials(n.name)}</span><span class="person-copy"><strong>${esc(n.name)}</strong><small>${esc(n.role)}</small></span></button>`).join('');
    document.querySelectorAll('[data-context]').forEach(b=>b.onclick=()=>pickContext(b.dataset.context));return;
  }
  document.querySelector('.panel-heading h2').textContent='People';
  document.getElementById('people-count').textContent=snapshot.ranked_contacts.length;
  document.getElementById('ranking-caption').textContent=query.expand?({recent:'Ordered by relationship event; unknown dates last',frequency:'Ordered by direct sessions; unknown metrics last',name:'Ordered by name'}[query.scope_sort]):query.mode==='current'?'Ordered by recent direct activity':'Ordered by longer-term activity';
  document.getElementById('people').innerHTML=snapshot.ranked_contacts.map(p=>{
    const scope=p.relationship_scope;
    const pending=scope?.paths?.some(path=>path.status==='pending');
    const details=query.expand?`${scopeTags(scope)}${pending?'<small class="scope-unconfirmed">Includes unconfirmed path</small>':''}<small class="scope-event">${esc(relationshipEvent(scope))}</small>`:`<span class="activity-line"><span style="width:${p[query.mode==='current'?'current_activity':'history_activity']}%"></span></span>`;
    return `<button class="person-row ${selectedId===p.id?'selected':''}" data-person="${esc(p.id)}"><span class="person-avatar">${initials(p.name)}</span><span class="person-copy"><strong>${esc(p.name)}</strong><small>${esc(p.role)}</small>${details}</span></button>`;
  }).join('')||`<p class="panel-caption">${query.expand?'No people in the selected scopes. Choose another scope or adjust the event filters.':'No matching people. Try another filter.'}</p>`;
  document.querySelectorAll('[data-person]').forEach(b=>b.onclick=()=>{inspectorDismissed=false;selectedId=b.dataset.person;selectedClaim='';graph.select(selectedId);renderPeople();renderInspector();});
}
function pathMarkup(path){
  const nodes=new Map(snapshot.nodes.map(n=>[n.id,n.name]));
  const claims=(path.claim_ids||[]).map(id=>snapshot.edges.find(e=>e.id===id)).filter(Boolean);
  return `<details class="scope-path ${path.status==='pending'?'scope-path-pending':''}"><summary>${esc(scopes[path.scope]||path.scope)}${path.status==='pending'?' · Unconfirmed':path.active===false?' · Historical':''}</summary><p class="scope-path-nodes">${(path.node_ids||[]).map(id=>esc(nodes.get(id)||id)).join(' → ')}</p><p>${esc(path.label||'Evidence-supported path')}</p><p class="muted">${path.overlap?`Membership overlap: ${esc(String(path.overlap).replaceAll('_',' '))}. `:''}${(path.claim_ids||[]).length} relationship(s) in this path.${path.last_event_at?' Relationship event: '+esc(path.last_event_at.slice(0,10))+'.':''}</p>${claims.map(edge=>claimMarkup(edge,snapshot.nodes)).join('')}</details>`;
}
function scopeInspector(scope){
  const interaction=scope?.interaction||{};
  const paths=scope?.paths||[],confirmed=paths.filter(p=>p.status!=='pending'),pending=paths.filter(p=>p.status==='pending');
  return `<section class="relationship-details"><h3>Why this person appears</h3>${scopeTags(scope)}<p>${(scope?.scope_reasons||['No relationship evidence available in this snapshot.']).map(esc).join('<br>')}</p><p>${esc(relationshipEvent(scope))}</p><dl><dt>Direct sessions with this focus</dt><dd>${interaction.sessions??'Unknown'}</dd><dt>Two-way sessions with this focus</dt><dd>${interaction.reciprocal_sessions??'Unknown'}</dd><dt>Latest direct interaction</dt><dd>${interaction.last_at?esc(interaction.last_at.slice(0,10)):'Unknown'}</dd></dl><p class="muted">${esc(interaction.coverage||'No observed pair metrics.')} Counts describe this exact pair; affiliation is not interaction.</p>${confirmed.length?'<h3>Supported relationship paths</h3>'+confirmed.map(pathMarkup).join(''):''}${pending.length?'<section class="unconfirmed-paths"><h3>Unconfirmed paths</h3><p>These paths include an unconfirmed claim. They do not establish an introduction or willingness to help.</p>'+pending.map(pathMarkup).join('')+'</section>':''}</section>`;
}
function activityInspector(person){
  return `<h3>Why this person appears</h3><p>${person.reasons.map(esc).join('<br>')}</p><dl><dt>Recent activity</dt><dd>${person.current_activity}/100</dd><dt>Longer-term activity</dt><dd>${person.history_activity}/100</dd><dt>Two-way sessions</dt><dd>${person.history.reciprocal_sessions}</dd><dt>Observed active days</dt><dd>${person.history.active_days}</dd></dl><p class="muted">${esc(person.history.label)}. Coverage: ${esc(person.history.coverage)}. Activity measures observed exchanges, not trust.</p>`;
}
function focusNeighborhood(node){
  const scope=node.kind==='project'?'project':node.kind==='organization'?'organization':query.scopes;
  selectedId=node.id;selectedClaim='';inspectorDismissed=false;
  document.getElementById('entity-lens').value='person';
  updateQuery({focus:node.id,expand:node.id,scopes:scope});
}
function renderInspector(){
  if(!snapshot)return;
  const restoreFocus=preserveFocus(inspector);
  const node=snapshot.nodes.find(n=>n.id===selectedId)||snapshot.ranked_contacts.find(n=>n.id===selectedId);
  const edge=snapshot.edges.find(e=>e.id===selectedClaim);
  document.body.classList.toggle('has-inspection',!inspectorDismissed&&!!(edge||(node&&node.id!==snapshot.owner_id)));
  if(edge){
    inspector.innerHTML=`<span class="entity-kind">Relationship evidence</span><h2>${esc(edge.relation)}</h2>${claimMarkup(edge,snapshot.nodes)}<p class="muted">This claim is ${esc(edge.status)}. ${snapshot.data_source==='real'?'Inspect the original source and its limitations.':'Its source is a fictional scenario record.'}</p>`;graph.select(edge.id);
  }else if(node){
    const person=snapshot.ranked_contacts.find(n=>n.id===node.id),edges=snapshot.edges.filter(e=>e.source===node.id||e.target===node.id);
    const explanation=person?(query.expand?scopeInspector(person.relationship_scope):activityInspector(person)):'';
    inspector.innerHTML=`<span class="entity-kind">${esc(node.kind)}${node.id===snapshot.owner_id?' / Network owner':''}</span><h2>${esc(node.name)}</h2><p class="muted">${esc(node.role)}</p>${explanation}<button id="expand-person">Focus neighborhood</button>${node.kind==='person'&&node.id!==snapshot.owner_id?` <a href="${esc(queryUrl('/inbox',{...query,focus:node.id}))}">Open conversation</a>`:''}<button class="ask-context" id="ask-context">Ask Claude about this ${esc(node.kind)}</button><div id="context-lens"></div><h3>Supported connections (${edges.length})</h3>${edges.map(e=>claimMarkup(e,snapshot.nodes)).join('')||'<p class="muted">No supported connections in this view.</p>'}`;
    document.getElementById('expand-person').onclick=()=>focusNeighborhood(node);
    document.getElementById('ask-context').onclick=()=>openAssistant({focus:node.id,as_of:query.as_of,mode:query.mode,name:node.name});
    mountContext(document.getElementById('context-lens'),{focus:node.id,as_of:query.as_of,mode:query.mode,include_pending:query.include_pending},pickContext);
  }else{inspector.innerHTML='<h2>Select a connection</h2><p>Choose a person or relationship to inspect evidence.</p>';}
  inspector.insertAdjacentHTML('afterbegin','<button class="inspector-close" aria-label="Close evidence panel" title="Close evidence panel">&times;</button>');
  inspector.querySelector('.inspector-close').onclick=()=>{inspectorDismissed=true;document.body.classList.remove('has-inspection');};
  bindEvidence(inspector,snapshot,query,expanded,id=>{selectedClaim=id;graph.select(id);syncUrl();});restoreFocus();syncUrl();
}
function renderExpansion(){
  document.body.classList.toggle('exploring-scopes',!!query.expand);
  document.getElementById('expansion-controls').hidden=!query.expand;
  const selected=query.scopes.split(',').filter(Boolean);
  document.querySelectorAll('[name=scopes]').forEach(input=>input.checked=selected.includes(input.value));
  document.getElementById('scope-window').value=String(query.scope_window);
  document.getElementById('scope-sort').value=query.scope_sort;
  document.getElementById('scope-min-sessions').value=String(query.min_sessions);
  document.getElementById('expand-more').disabled=Object.keys(scopes).every(key=>selected.includes(key));
  document.getElementById('scope-empty').hidden=selected.length>0;
  document.getElementById('scope-note').textContent='The event window applies only to direct interaction and collaboration or introduction. Shared contexts remain visible; minimum sessions applies only to direct interaction. Shared affiliation does not establish interaction or acquaintance.';
  const counts=snapshot.expansion?.counts,omitted=snapshot.expansion?.omitted_counts;
  document.getElementById('scope-counts').textContent=counts?Object.entries(scopes).map(([key,label])=>`${label}: ${counts[key]??0}`).join(' · ')+(omitted&&(omitted.candidates||omitted.paths)?` · Not shown: ${omitted.candidates||0} people, ${omitted.paths||0} paths`:''):'';
  const search=document.querySelector('[name=search]');search.disabled=!!query.expand;
  search.title=query.expand?'Name search is paused while exploring this focus. Use Back to search to resume.':'';
}
function pickContext(id){
  inspectorDismissed=false;selectedId=id;selectedClaim='';graph.select(id);
  const node=snapshot.nodes.find(n=>n.id===id)||[...snapshot.options.organizations,...snapshot.options.projects].find(n=>n.id===id);
  if(!snapshot.nodes.some(n=>n.id===id)||!id.startsWith('person:'))focusNeighborhood({...node,id,kind:node?.kind||(id.startsWith('project:')?'project':id.startsWith('org:')?'organization':'person')});
  else{renderPeople();renderInspector();}
}
document.getElementById('filters').onsubmit=e=>e.preventDefault();
let timer;document.querySelector('[name=search]').oninput=e=>{clearTimeout(timer);timer=setTimeout(()=>updateQuery({search:e.target.value,expand:''}),180);};
for(const key of ['function','organization','project'])document.querySelector(`[name=${key}]`).onchange=e=>updateQuery({[key]:e.target.value,expand:''});
document.getElementById('clear-filters').onclick=()=>{for(const key of ['search','function','organization','project'])document.querySelector(`[name=${key}]`).value='';updateQuery({search:'',function:'',organization:'',project:'',expand:'',focus:'person:owner'});};
document.querySelectorAll('[data-mode]').forEach(button=>button.onclick=()=>{document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('active',b===button));updateQuery({mode:button.dataset.mode});});
document.getElementById('as-of').onchange=e=>{if(e.target.value)updateQuery({as_of:e.target.value+'T23:59:59Z',live:'0'});};
document.getElementById('live-network')?.addEventListener('click',()=>updateQuery({as_of:new Date().toISOString(),live:'1'}));
document.getElementById('hypotheses').onchange=e=>updateQuery({include_pending:String(e.target.checked)});
document.getElementById('fit').onclick=()=>graph.fit();
for(const action of ['reply','reset'])if(document.getElementById(action))document.getElementById(action).onclick=async()=>{try{const response=await fetch('/network/demo/'+action,{method:'POST'});if(!response.ok)throw new Error('Scenario action failed. Retry.');client.refresh();setTimeout(()=>setStatus('Scenario updated. '+(action==='reply'?'Maya replied; recent activity has changed.':'Initial fictional data restored.')),500);}catch(error){setStatus(error.message,true);}};
window.addEventListener('pagehide',()=>{client.destroy();graph.destroy();});
document.getElementById('entity-lens').onchange=renderPeople;
document.querySelectorAll('[name=scopes]').forEach(input=>input.onchange=()=>updateQuery({scopes:[...document.querySelectorAll('[name=scopes]:checked')].map(i=>i.value).join(',')}));
document.getElementById('scope-window').onchange=e=>updateQuery({scope_window:e.target.value});
document.getElementById('scope-sort').onchange=e=>updateQuery({scope_sort:e.target.value});
document.getElementById('scope-min-sessions').onchange=e=>{if(e.target.reportValidity())updateQuery({min_sessions:e.target.value||'0'});};
document.getElementById('expand-more').onclick=()=>{
  const selected=query.scopes.split(',').filter(Boolean),next=Object.keys(scopes).find(key=>!selected.includes(key));
  if(next)updateQuery({scopes:Object.keys(scopes).filter(key=>selected.includes(key)||key===next).join(',')});
};
document.getElementById('exit-expansion').onclick=()=>updateQuery({expand:''});
document.getElementById('ask-network').onclick=()=>openAssistant({focus:selectedId||query.focus,as_of:query.as_of,mode:query.mode,name:snapshot?.nodes.find(n=>n.id===selectedId)?.name||'Your network'});
window.addEventListener('network-profile-updated',event=>{
  if(!event.detail?.as_of)return;
  query.as_of=event.detail.as_of;document.getElementById('as-of').value=query.as_of.slice(0,10);updateQuery({as_of:query.as_of});
});
window.addEventListener('network-health',event=>{
  const health=event.detail;
  if(snapshot?.data_source==='real')setStatus(`Local source · Snapshot ${snapshot.version} · Last refresh ${health.last_success_at||'pending'}${health.error_code||health.stale?' · Refresh delayed; showing last successful state.':''}${snapshot.truncated?' · Bounded view.':''}`);
});
