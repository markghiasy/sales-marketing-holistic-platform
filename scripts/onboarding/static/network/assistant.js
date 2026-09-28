import {escapeHtml as esc, queryUrl} from './client.js';

let activeAssistant;
export function openAssistant({focus='person:owner', as_of='2026-09-27T12:00:00Z', mode='current', name='Your network', question=''}={}) {
  activeAssistant?.();
  const returnFocus=document.activeElement, panel=document.createElement('aside');
  panel.className='network-assistant'; panel.setAttribute('aria-label','Network strategy assistant');
  let closed=false, controller, turns=[];
  panel.innerHTML=`<header><div><span class="agent-kicker">NETWORK INTELLIGENCE</span><h2>Think through your next move.</h2></div><button data-close aria-label="Close assistant">&times;</button></header>
    <div class="agent-scope"><strong>${esc(name)}</strong><span>Known by ${esc(as_of.slice(0,10))} &middot; ${mode==='history'?'Relationship history':'Current relationships'} &middot; Confirmed synthetic evidence</span></div>
    <p class="agent-provider" role="status">Checking Claude connection…</p>
    <div class="agent-thread" aria-live="polite"><div class="agent-welcome"><h3>From connections to a plan.</h3><p>Explore who could help, what the evidence supports, and what you still need to learn.</p>
    <button data-prompt="I am starting Cybertest: authorized adversarial AI-agent security testing for vibe coding. Who could help, what capabilities are unverified, and how should I expand my network?">Plan a Cybertest team <span>↗</span></button>
    <button data-prompt="For the selected context, what responsibilities and deliveries are recorded, and what should I follow up next?">Review work and follow-ups <span>↗</span></button></div></div>
    <form class="agent-form"><label for="agent-question">Ask about a goal or this context</label><textarea id="agent-question" maxlength="2000" rows="3" placeholder="What would it take to move this project forward?" required></textarea><div><small>Uses Claude · Sources stay inspectable</small><button class="agent-send" type="submit">Ask Claude</button></div></form>`;
  document.body.append(panel);
  const input=panel.querySelector('textarea'), thread=panel.querySelector('.agent-thread'), send=panel.querySelector('.agent-send');
  input.value=question; input.focus();
  function close(){closed=true;controller?.abort();panel.remove();document.removeEventListener('keydown',escape);returnFocus?.focus();activeAssistant=null;}
  function escape(e){if(e.key==='Escape'&&panel.contains(document.activeElement))close();}
  activeAssistant=close;
  panel.querySelector('[data-close]').onclick=close;document.addEventListener('keydown',escape);
  fetch('/network/agent/status.json').then(r=>r.json()).then(s=>{if(closed)return;panel.querySelector('.agent-provider').textContent=s.configured?`Claude configured · ${s.model} · ${s.remaining} questions left in this session`:'Claude is not configured. Start the demo with its local env file.';}).catch(()=>{if(!closed)panel.querySelector('.agent-provider').textContent='Could not check Claude availability.';});
  panel.querySelectorAll('[data-prompt]').forEach(b=>b.onclick=()=>{input.value=b.dataset.prompt;input.focus();});
  panel.querySelector('form').onsubmit=async e=>{
    e.preventDefault();const text=input.value.trim();if(!text||send.disabled)return;
    panel.querySelector('.agent-welcome')?.remove();
    const item=document.createElement('article');item.className='agent-turn';
    item.innerHTML=`<p class="agent-question">${esc(text)}</p><div class="agent-answer"><p role="status">Understanding the goal, querying evidence, and checking the answer…</p></div>`;
    thread.append(item);item.scrollIntoView({block:'nearest'});send.disabled=true;send.textContent='Thinking…';controller=new AbortController();
    try{
      const response=await fetch('/network/agent.json',{method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,body:JSON.stringify({question:text,focus,as_of,mode,history:turns.slice(-4)})});
      const data=await response.json();if(!response.ok)throw new Error(data.error||'Claude is unavailable.');if(closed)return;
      const entities=new Map(data.entities.map(n=>[n.id,n.name])), sources=new Map(data.evidence.map(s=>[s.id,s]));
      item.querySelector('.agent-answer').innerHTML=`<span class="agent-advisory">Strategy suggestion · validate before acting</span><p class="agent-summary">${esc(data.summary)}</p>
        ${data.findings.length?'<h3>What the evidence supports</h3>':''}${data.findings.map(f=>`<section class="agent-finding"><p>${esc(f.text)}</p><div class="agent-entity-links">${f.entity_ids.map(id=>`<a href="${esc(queryUrl('/network',{focus:id,expand:id,depth:2,as_of,mode}))}">${esc(entities.get(id))} ↗</a>`).join('')}</div><details><summary>${f.evidence_ids.length} source${f.evidence_ids.length===1?'':'s'}</summary>${f.evidence_ids.map(id=>{const s=sources.get(id);return `<small>${esc(s.channel)} · ${esc(s.at.slice(0,10))}</small><blockquote>${esc(s.text)}</blockquote>`;}).join('')}</details></section>`).join('')}
        ${data.gaps.length?`<h3>What is not established yet</h3><ul>${data.gaps.map(g=>`<li>${esc(g)}</li>`).join('')}</ul>`:''}
        ${data.next_steps.length?`<h3>Suggested next moves</h3><ol>${data.next_steps.map(g=>`<li>${esc(g)}</li>`).join('')}</ol>`:''}
        ${data.clarification?`<p class="agent-clarification">${esc(data.clarification)}</p>`:''}
        <details class="agent-trace"><summary>How this answer was grounded</summary><p>Snapshot ${esc(data.version)} · ${esc(data.model)} · ${data.usage.input_tokens+data.usage.output_tokens} tokens</p><ul>${data.trace.map(t=>`<li>${esc(t.kind)} · ${esc(t.terms.length?t.terms.join(', '):entities.get(t.entity_id)||t.entity_id)}</li>`).join('')}</ul>${data.retrieval?`<p>${data.retrieval.scope.scanned_people} contacts searched &middot; ${data.retrieval.budget.selected_records} evidence records included${data.retrieval.budget.omitted_records?' &middot; '+data.retrieval.budget.omitted_records+' records omitted to fit the context':''}</p><ul class="agent-coverage">${data.retrieval.coverage.map(c=>`<li><strong>${esc(c.label)}</strong>: ${esc(({matching_evidence:'Matching records found; capability still needs validation',searched_no_match:'No match in searched records',budget_omitted:'Matching records found but omitted from this answer',not_searched:'Not fully searched'})[c.status]||c.status)}</li>`).join('')}</ul>`:''}<p>References are checked against retrieved records; relevance still needs human judgment.</p></details>`;
      turns.push({question:text,answer:[data.summary,...data.next_steps].join('\n').slice(0,1500)});input.value='';
      item.querySelector('.agent-answer').scrollIntoView({block:'start'});
    }catch(error){if(!closed&&error.name!=='AbortError')item.querySelector('.agent-answer').innerHTML=`<p role="alert">${esc(error.message)}</p>`;}
    finally{if(!closed){send.disabled=false;send.textContent='Ask Claude';input.focus();}}
  };
  return {close};
}
