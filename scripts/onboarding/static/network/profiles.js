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
    if(data.data_source==='real'){renderReal(data);return;}
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
  function renderReal(data){
    const names=new Map((data.entities||[]).map(e=>[e.id,e.name]));
    const sourceLink=id=>`<a target="_blank" rel="noopener" href="${esc(queryUrl('/network/evidence/'+encodeURIComponent(id)+'.json',{as_of:query.as_of,version:data.version}))}">Open original source</a>`;
    container.innerHTML=`<section class="strategic-profile"><h3>Strategic profile</h3><p class="profile-note">${esc(data.coverage)} Proposals require review; decisions are saved across restarts.</p>
      ${(data.assertions||[]).map(a=>`<article class="profile-assertion"><span class="profile-status">Confirmed</span><strong>${esc(a.label)}</strong><p>${esc(facetNames[a.facet]||a.facet)} · ${esc(names.get(a.subject_id)||a.subject_id)}</p><blockquote>${esc(a.quote)}</blockquote>${a.evidence_ids.map(sourceLink).join(' ')}</article>`).join('')||'<p>No confirmed strategic assertions yet.</p>'}
      <details class="source-selection"><summary>Select messages to extract draft knowledge</summary><p class="profile-note">Select up to 12 sources. Claude receives only the selected excerpts and this bounded entity context.</p>${(data.source_choices||[]).map(s=>`<label class="profile-source"><input type="checkbox" value="${esc(s.id)}"> ${esc(s.channel)} · ${esc(s.at?.slice(0,10))}<blockquote>${esc((s.text||'').slice(0,4000))}${(s.text||'').length>4000?'… (first 4000 characters)':''}</blockquote></label>`).join('')||'<p>No eligible sources in this slice.</p>'}<button type="button" class="profile-extract">Extract selected sources with Claude</button></details><p class="profile-feedback" role="status"></p>
      <h4>Review queue</h4>${(data.proposals||[]).map(p=>{const b=p.payload.batch;const localNames=new Map([...names,...b.entities.map(e=>[e.id,e.name])]);return `<article class="profile-proposal" data-proposal="${esc(p.id)}"><span class="profile-status">${esc(p.status)}</span>${b.entities.map(e=>`<p>Proposed ${esc(e.kind)}: <strong>${esc(e.name)}</strong></p><blockquote>${esc(e.quote)}</blockquote>${sourceLink(e.evidence_id)}<label>Resolve identity<select data-binding="${esc(e.id)}"><option value="">Choose an identity</option><option value="create">Create a distinct ${esc(e.kind)}</option>${data.entities.filter(n=>n.kind===e.kind).map(n=>`<option value="${esc(n.id)}">Use existing: ${esc(n.name)} (${esc(n.id)})</option>`).join('')}</select></label>`).join('')}${b.relations.map(r=>`<p>${esc(localNames.get(r.source_id)||r.source_id)} · ${esc(r.relation)} · ${esc(localNames.get(r.target_id)||r.target_id)}</p><blockquote>${esc(r.quote)}</blockquote>${sourceLink(r.evidence_id)}`).join('')}${b.assertions.map(a=>`<p>${esc(localNames.get(a.subject_id)||a.subject_id)} · ${esc(a.facet)}: ${esc(a.label)}</p><blockquote>${esc(a.quote)}</blockquote>${sourceLink(a.evidence_id)}`).join('')}<p class="profile-note">Confirm only if the quotations support all claims and identity choices in this batch. Reject and re-extract if attribution is wrong.</p><div class="profile-actions">${p.status==='pending'?'<button type="button" data-decision="confirm">Confirm batch</button>':''}${p.status!=='rejected'?'<button type="button" data-decision="reject">Reject batch</button>':''}</div></article>`;}).join('')||'<p>No proposals in this view.</p>'}</section>`;
    container.querySelector('.profile-extract').onclick=()=>{
      const ids=[...container.querySelectorAll('.profile-source input:checked')].map(el=>el.value);
      if(!ids.length||ids.length>12){container.querySelector('.profile-feedback').textContent='Select between 1 and 12 sources.';return;}
      mutate('/network/profile/extract',{focus:query.focus,as_of:query.as_of,mode:query.mode,evidence_ids:ids});
    };
    container.querySelectorAll('[data-decision]').forEach(button=>button.onclick=()=>{
      const row=button.closest('[data-proposal]'),bindings=Object.fromEntries([...row.querySelectorAll('[data-binding]')].map(el=>[el.dataset.binding,el.value]));
      if(button.dataset.decision==='confirm'&&Object.values(bindings).some(v=>!v)){container.querySelector('.profile-feedback').textContent='Choose an identity for each proposed entity.';return;}
      mutate('/network/profile/review',{proposal_id:row.dataset.proposal,expected_version:version,decision:button.dataset.decision,entity_bindings:button.dataset.decision==='confirm'?bindings:{}});
    });
  }
  async function refresh(){
    controller?.abort();controller=new AbortController();
    try{render(await json(queryUrl('/network/profile.json',query)));}
    catch(error){if(current()&&error.name!=='AbortError'){container.innerHTML=`<section class="strategic-profile"><h3>Strategic profile</h3><p role="alert">${esc(error.message)}</p><button type="button" class="profile-retry">Retry profile</button></section>`;container.querySelector('button').onclick=refresh;}}
  }
  async function mutate(url,body){
    if(busy)return;busy=true;
    const feedback=container.querySelector('.profile-feedback');feedback.textContent=url.endsWith('extract')?'Extracting draft assertions from selected sources…':'Saving review…';
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
