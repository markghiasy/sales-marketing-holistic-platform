import {escapeHtml as esc,queryUrl,showEvidence} from './client.js';

export async function mountContext(container, query, onPick) {
  container.innerHTML='<p class="muted">Loading this context…</p>';
  try {
    const response=await fetch(queryUrl('/network/context.json',query));
    const data=await response.json();if(!response.ok)throw new Error(data.error);if(!container.isConnected)return;
    container.innerHTML=`${data.kind==='person'?`<h3>Roles & shared context</h3><div class="lens-tags">${data.tags.map(t=>`<span>${esc(t.label)}</span>`).join('')}</div>${data.contexts.map(c=>`<button class="lens-context" data-pick="${esc(c.entity.id)}">${esc(c.entity.name)} <small>${c.shared_with_owner?'Shared with you':'Recorded affiliation'}</small></button>`).join('')}`:''}
    ${data.kind!=='person'?`<h3>${data.kind==='project'?'Team & responsibilities':'People & functions'} (${data.members.length})</h3><p class="lens-note">Activity below is communication with you.</p>${data.members.map(m=>`<div class="lens-member"><button data-pick="${esc(m.id)}">${esc(m.name)}</button><small>${esc(m.areas.join(' · ')||m.tags.filter(t=>t.kind==='function').map(t=>t.label).join(' · ')||'Responsibility not recorded')}</small><div class="lens-metrics"><span>${m.current_activity}/100 activity</span>${data.kind==='project'?`<span>${m.deliveries} recorded deliveries</span>`:''}</div></div>`).join('')}`:''}
    ${data.kind==='project'||data.work.length?`<h3>Work & follow-ups</h3><div class="lens-stat-row"><span><strong>${data.deliveries}</strong> recorded deliveries</span><span><strong>${data.follow_ups.length}</strong> follow-ups</span></div>${data.work.map(w=>`<section class="lens-work"><span class="work-state ${esc(w.status)}">${esc(w.status)}</span><p>${esc(w.title)}</p><small>${esc(data.members.find(m=>m.id===w.person_id)?.name||data.entity.name)} · ${esc(w.area)}${w.due?' · Due '+esc(w.due):''}${data.follow_ups.find(r=>r.id===w.id)?.overdue?' · Overdue':''}</small><details data-work="${esc(w.id)}"><summary>Source update</summary><div></div></details></section>`).join('')||'<p class="muted">No work records known at this date.</p>'}`:''}
    <p class="lens-note">${esc(data.coverage)}</p>`;
    container.querySelectorAll('[data-pick]').forEach(b=>b.onclick=()=>onPick(b.dataset.pick));
    container.querySelectorAll('[data-work]').forEach(d=>d.ontoggle=async()=>{if(!d.open)return;try{await showEvidence(d.querySelector('div'),data.work.find(w=>w.id===d.dataset.work),query);}catch(e){d.querySelector('div').textContent=e.message;}});
  } catch(error){if(container.isConnected)container.textContent=error.message;}
}
