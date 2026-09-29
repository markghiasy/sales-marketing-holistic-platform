import {defaultDate, defaultOwner, realNetwork} from './client.js';
import {escapeHtml as esc, queryUrl, showEvidence} from './client.js';
import {openAssistant} from './assistant.js';

export function mountDiscovery(container, {onClose, onOpenContact}) {
  let controller, generation = 0, closed = false;
  const examples = [
    'Find an accountant with logistics experience, preferably someone I worked with before',
    'People on Harbour expansion',
    'Alex Morgan',
  ];
  container.innerHTML = `<section class="discovery-panel" role="dialog" aria-modal="true" aria-labelledby="discovery-title">
    <header><div><span class="discovery-kicker">Your network</span><h2 id="discovery-title">Find people and opportunities</h2></div><button class="discovery-close" aria-label="Close search">&times;</button></header>
    <p class="discovery-intro">Search names, expertise, shared work or a business goal. See the evidence and what still needs checking.</p>
    <form class="discovery-form"><label for="discovery-query">Search your network</label><div><input id="discovery-query" name="query" maxlength="2000" autocomplete="off" placeholder="Who can help with a logistics AI security pilot?" required><button type="submit">Search</button></div></form>
    <div class="discovery-examples">${examples.map((q, i) => `<button type="button" data-example="${i}">${i === 0 ? 'Logistics + accounting + past collaboration' : esc(q)}</button>`).join('')}</div>
    <div class="discovery-output" aria-live="polite"><div class="discovery-empty"><h3>Start with the work you need to do.</h3><p>Try a person, a company or a combination of skills and relationships. English and Chinese are supported for these search conditions.</p></div></div>
    <button type="button" class="discovery-agent">Ask Claude about a goal or strategy ↗</button>
    <footer>${realNetwork()?'Bounded search over observed records.':'Synthetic data.'} Search checks names and supported conditions directly; goals and complex questions continue with Claude using this session's question budget.</footer>
  </section>`;
  const input = container.querySelector('input');
  const output = container.querySelector('.discovery-output');
  container.querySelector('.discovery-agent').onclick=()=>{const p=new URLSearchParams(location.search);const question=input.value;onClose();openAssistant({question,focus:p.get('focus')||defaultOwner(),as_of:p.get('as_of')||defaultDate(),mode:p.get('mode')||'current'});};
  container.querySelector('.discovery-close').onclick = onClose;
  container.querySelector('form').onsubmit = event => { event.preventDefault(); search(); };
  container.querySelectorAll('[data-example]').forEach(button => button.onclick = () => {
    input.value = examples[Number(button.dataset.example)]; search();
  });
  // Keep keyboard navigation inside the modal; closing returns focus to its launcher.
  const keydown = event => {
    if (event.key === 'Escape') { event.preventDefault(); onClose(); return; }
    if (event.key !== 'Tab') return;
    const controls = [...container.querySelectorAll('button,input,a,summary')].filter(el => el.offsetParent !== null && !el.disabled);
    const first = controls[0], last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  };
  container.addEventListener('keydown', keydown);
  input.focus();

  async function search() {
    const text = input.value.trim();
    if (!text) { input.focus(); return; }
    controller?.abort();
    controller = new AbortController();
    const ticket = ++generation;
    output.innerHTML = '<p role="status">Finding supported matches…</p>';
    try {
      const asOf = new URLSearchParams(location.search).get('as_of') || defaultDate();
      const response = await fetch(queryUrl('/network/search.json', {q: text, as_of: asOf, mode: new URLSearchParams(location.search).get('mode') || 'current'}), {signal: controller.signal});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Search unavailable. Please retry.');
      if (closed || ticket !== generation) return;
      if(data.status==='needs_clarification'){
        const p=new URLSearchParams(location.search);
        onClose();
        openAssistant({question:text,autoSubmit:true,focus:p.get('focus')||defaultOwner(),as_of:asOf,mode:p.get('mode')||'current'});
        return;
      }
      render(data);
    } catch (error) {
      if (!closed && ticket === generation && error.name !== 'AbortError') {
        output.innerHTML = `<p role="alert">${esc(error.message)}</p>`;
      }
    }
  }

  function render(data) {
    const conditions = `<div class="discovery-conditions"><h3>Understood conditions</h3><div>${data.criteria.map(c => `<span class="condition ${c.mode}"><small>${c.mode === 'prefer' ? 'Preferred' : 'Required'}</small> ${esc(c.value)}</span>`).join('') || '<span>No conditions recognized yet.</span>'}</div></div>`;
    if (data.status === 'needs_clarification') {
      output.innerHTML = `${conditions}<div class="discovery-clarify"><h3>Please clarify your search</h3><p>Not yet understood: <strong>${esc(data.unresolved)}</strong></p><p>No results are shown because that condition has not been checked. Edit the question or try one of the examples.</p></div>`;
      return;
    }
    output.innerHTML = `${conditions}<div class="discovery-results-heading"><h3>${data.results.length} matching contacts</h3><span>Preferences first, then recent activity</span></div>${data.results.map(person => `
      <article class="discovery-result" data-result-person="${esc(person.id)}">
        <div class="discovery-person"><div class="discovery-avatar">${esc(person.name.split(' ').map(s => s[0]).join(''))}</div><div><h3>${esc(person.name)}</h3><p>${esc(person.role)}</p></div></div>
        <div class="discovery-tags">${person.tags.map(t => `<span class="contact-tag" data-kind="${esc(t.kind)}" title="${esc(t.kind + (t.relation ? ': ' + t.relation : ''))}">${esc(t.label)}</span>`).join('')}</div>
        <ul class="match-reasons">${person.reasons.map(r => `<li><span>${r.mode === 'prefer' ? 'Preference met' : 'Match'}</span> ${esc(r.text)}</li>`).join('')}</ul>
        ${person.unmet_preferences.length ? `<p class="unmet-preference">Not established: ${person.unmet_preferences.map(esc).join(', ')}. This was a preference, so the person remains in the results.</p>` : ''}
        <details class="matching-evidence"><summary>View matching evidence</summary><div class="matching-evidence-body"></div></details>
        <div class="discovery-actions"><button data-conversation="${esc(person.id)}">Open conversation</button><a href="${esc(person.network_url)}">View in graph</a></div>
      </article>`).join('') || '<div class="discovery-empty"><p>No confirmed contacts meet all required conditions. Try removing a condition; missing evidence does not prove someone lacks that experience.</p></div>'}`;
    output.querySelectorAll('[data-conversation]').forEach(button => button.onclick = () => onOpenContact(button.dataset.conversation));
    output.querySelectorAll('.matching-evidence').forEach((details, index) => {
      let loaded = false;
      details.ontoggle = async () => {
        if (!details.open || loaded) return;
        const person = data.results[index], body = details.querySelector('.matching-evidence-body');
        body.textContent = 'Loading source messages…';
        try {
          const ids = [...new Set(person.reasons.flatMap(r => r.evidence_ids))];
          await showEvidence(body, {evidence_ids: ids}, {as_of: data.as_of, mode: data.mode});
          loaded = true;
        } catch (error) { if (body.isConnected) body.textContent = error.message; }
      };
    });
  }
  return {destroy() { closed = true; generation++; controller?.abort(); container.removeEventListener('keydown', keydown); }};
}
