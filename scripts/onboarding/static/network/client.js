export const escapeHtml=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const initials=name=>name.split(' ').map(s=>s[0]).slice(0,2).join('');
export function readQuery(){const p=new URLSearchParams(location.search);return {focus:p.get('focus')||'person:owner',as_of:p.get('as_of')||'2026-09-27T12:00:00Z',search:p.get('search')||'',function:p.get('function')||'',organization:p.get('organization')||'',project:p.get('project')||'',mode:p.get('mode')||'current',include_pending:p.get('include_pending')||'false',expand:p.get('expand')||''};}
export function queryUrl(path,query){return path+'?'+new URLSearchParams(query).toString();}
export function createNetworkClient({query,onSnapshot,onError}){
  let state={...query},generation=0,controller,closed=false,lastVersion=-1;
  async function refresh(){const ticket=++generation;controller?.abort();controller=new AbortController();try{const response=await fetch(queryUrl('/network/graph.json',state),{signal:controller.signal});if(!response.ok)throw new Error((await response.json()).error||'Network unavailable');const body=await response.json();if(!closed&&ticket===generation&&body.version>=lastVersion){lastVersion=body.version;onSnapshot(body,{...state});}}catch(error){if(error.name!=='AbortError'&&!closed&&ticket===generation)onError(error.message);}}
  const events=new EventSource('/network/events');events.addEventListener('update',refresh);events.addEventListener('open',refresh);events.onerror=()=>{if(!closed)onError('Connection interrupted. Showing the last snapshot; reconnecting automatically.');};
  refresh();
  return {setQuery(patch){state={...state,...patch};refresh();},refresh,destroy(){closed=true;controller?.abort();events.close();}};
}
export function claimMarkup(edge,nodes){const names=new Map(nodes.map(n=>[n.id,n.name]));return `<div class="claim-item"><strong>${escapeHtml(names.get(edge.source)||edge.source)} · ${escapeHtml(edge.relation)}</strong><small>${escapeHtml(names.get(edge.target)||edge.target)} <span class="claim-state ${edge.status}">${edge.status==='pending'?'Unconfirmed':edge.active?'Current':'Historical'}</span></small><small>Effective: ${edge.valid_from?edge.valid_from.slice(0,10):'unknown'}${edge.valid_to?' to '+edge.valid_to.slice(0,10):''}<br>Known since ${edge.observed_at.slice(0,10)}</small><button data-evidence="${escapeHtml(edge.id)}">View evidence</button><div data-evidence-body="${escapeHtml(edge.id)}"></div></div>`;}
export async function showEvidence(container,edge,query){
  const results=await Promise.all(edge.evidence_ids.map(async id=>{const response=await fetch(queryUrl('/network/evidence/'+encodeURIComponent(id)+'.json',{as_of:query.as_of}));if(!response.ok)throw new Error('Evidence unavailable for this date.');return response.json();}));
  if(!container.isConnected)return;
  container.innerHTML=results.map(e=>`<div class="evidence-meta">Fictional ${escapeHtml(e.channel)} message · ${escapeHtml(e.at.slice(0,10))}</div><blockquote class="evidence-quote">${escapeHtml(e.text)}</blockquote>`).join('');
}
