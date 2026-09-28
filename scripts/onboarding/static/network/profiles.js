import {escapeHtml as esc, queryUrl} from './client.js';

const facetNames={need:'Needs',resource:'Resources',decision_role:'Decision roles',relationship:'Relationships',experience:'Experience',constraint:'Constraints'};
const mounts=new WeakMap();
const expandedAssertions=new Set();

export function mountProfile(container, initialQuery) {
  mounts.get(container)?.destroy();
  let query={...initialQuery}, controller, closed=false, version, busy=false;
  const current=()=>!closed&&container.isConnected;
  async function json(url, options={}) {
    const response=await fetch(url,{...options,signal:controller.signal});
    const data=await response.json();
    if(!response.ok)throw new Error(data.error||'Profile unavailable. Please retry.');
    return data;
  }
  function render(data){
    if(!current())return;
    version=data.version;
    const entities=new Map((data.entities||[]).map(e=>[e.id,e.name]));
    if(data.entity)entities.set(data.entity.id,data.entity.name);
    const sources=new Map((data.evidence||[]).map(e=>[e.id,e]));
    container.innerHTML=`<section class="strategic-profile"><h3>Strategic profile</h3><p class="profile-note">Synthetic demo. Review changes stay in memory; this profile resets on restart. Authored examples are not automatic extraction results.</p><button type="button" class="profile-extract">Extract draft assertions with Claude</button><p class="profile-feedback" role="status"></p>
      ${Object.entries(facetNames).map(([facet,label])=>{const rows=(data.assertions||[]).filter(a=>a.facet===facet);return rows.length?`<section class="profile-facet"><h4>${label}</h4>${rows.map(a=>`<article class="profile-assertion" data-assertion="${esc(a.id)}"><span class="profile-status" data-status="${esc(a.status)}">${esc(a.status)}</span><strong>${esc(a.label)}</strong><p class="profile-subject">About ${esc(entities.get(a.subject_id)||a.subject_id)}${a.context_id?' · Context: '+esc(entities.get(a.context_id)||a.context_id):''}</p><p class="profile-meta">${esc((a.basis||'').replaceAll('_',' '))}${a.claimant_id?' · Reported by '+esc(entities.get(a.claimant_id)||a.claimant_id):''} · ${a.active?'Current':'Historical'}${a.valid_from?' · From '+esc(a.valid_from.slice(0,10)):''}${a.valid_to?' to '+esc(a.valid_to.slice(0,10)):''}</p><details><summary>Source and review</summary><blockquote>${esc(a.quote)}</blockquote>${(a.evidence_ids||[]).map(id=>{const s=sources.get(id);return s?`<a href="${esc(queryUrl('/network/evidence/'+encodeURIComponent(id)+'.json',{as_of:query.as_of}))}" target="_blank" rel="noopener">${esc(s.channel)} · ${esc(s.at?.slice(0,10))}</a><blockquote>${esc(s.text)}</blockquote>`:'<p>Source unavailable at this date.</p>';}).join('')}<label>Correct subject<select aria-label="Correct subject">${[...entities].map(([id,name])=>`<option value="${esc(id)}"${id===a.subject_id?' selected':''}>${esc(name)}</option>`).join('')}</select></label><div class="profile-actions">${a.status!=='confirmed'?'<button type="button" data-review="confirmed">Confirm</button>':'<button type="button" data-review="confirmed">Save correction</button>'}${a.status!=='rejected'?'<button type="button" data-review="rejected">Reject</button>':''}</div></details></article>`).join('')}</section>`:'';}).join('')||'<p class="profile-note">No strategic assertions recorded at this date.</p>'}
      <p class="profile-note">${esc(typeof data.coverage==='string'?data.coverage:'Only source-backed records known at this date are shown.')} Pending and rejected assertions are excluded from recommendations.</p></section>`;
    container.querySelector('.profile-extract').onclick=()=>mutate('/network/profile/extract',{focus:query.focus,as_of:query.as_of,mode:query.mode});
    container.querySelectorAll('[data-assertion]').forEach(row=>{
      const details=row.querySelector('details');details.open=expandedAssertions.has(row.dataset.assertion);
      details.ontoggle=()=>{if(!row.isConnected)return;if(details.open)expandedAssertions.add(row.dataset.assertion);else expandedAssertions.delete(row.dataset.assertion);};
    });
    container.querySelectorAll('[data-review]').forEach(button=>button.onclick=()=>{
      const row=button.closest('[data-assertion]');
      mutate('/network/profile/review',{id:row.dataset.assertion,status:button.dataset.review,subject_id:row.querySelector('select').value,version});
    });
  }
  async function refresh(){
    controller?.abort();controller=new AbortController();
    try{render(await json(queryUrl('/network/profile.json',query)));}
    catch(error){if(current()&&error.name!=='AbortError'){container.innerHTML=`<section class="strategic-profile"><h3>Strategic profile</h3><p role="alert">${esc(error.message)}</p><button type="button" class="profile-retry">Retry profile</button></section>`;container.querySelector('button').onclick=refresh;}}
  }
  async function mutate(url,body){
    if(busy)return;busy=true;
    const feedback=container.querySelector('.profile-feedback');feedback.textContent=url.endsWith('extract')?'Extracting draft assertions from synthetic sources…':'Saving review…';
    container.querySelectorAll('button,select').forEach(el=>el.disabled=true);
    controller?.abort();controller=new AbortController();
    try{
      const data=await json(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(data.as_of)query.as_of=data.as_of;
      // SSE can remount the lens before this POST returns. Date/version propagation
      // belongs to the completed mutation, even if its original view is gone.
      window.dispatchEvent(new CustomEvent('network-profile-updated',{detail:{as_of:query.as_of,version:data.version}}));
      if(!current())return;
      if(data.assertions)render(data);else await refresh();
    }catch(error){if(current()&&error.name!=='AbortError'){feedback.setAttribute('role','alert');feedback.textContent=error.message;}}
    finally{busy=false;if(current())container.querySelectorAll('button,select').forEach(el=>el.disabled=false);}
  }
  container.innerHTML='<p class="profile-note">Loading strategic profile…</p>';
  const instance={destroy(){closed=true;controller?.abort();}};mounts.set(container,instance);refresh();return instance;
}
