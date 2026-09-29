export const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const initials = name => name.split(' ').map(s => s[0]).slice(0, 2).join('');
export const realNetwork = () => Boolean(window.NETWORK_CONFIG?.real);
export const defaultDate = () => realNetwork() ? new Date().toISOString() : '2026-09-27T12:00:00Z';
export const defaultOwner = () => window.NETWORK_CONFIG?.owner_id || 'person:owner';
export function readQuery() {
  const p = new URLSearchParams(location.search);
  return {
    focus: p.get('focus') || defaultOwner(), origin: p.get('origin') || '',
    as_of: p.get('as_of') || defaultDate(), search: p.get('search') || '',
    live: realNetwork() && (!p.has('as_of') || p.get('live')==='1') ? '1' : '0',
    function: p.get('function') || '', organization: p.get('organization') || '',
    project: p.get('project') || '', mode: p.get('mode') || 'current',
    include_pending: p.get('include_pending') || 'false', expand: p.get('expand') || '',
    scopes: p.has('scopes') ? p.get('scopes') : 'direct,explicit',
    scope_window: p.get('scope_window') || '0', scope_sort: p.get('scope_sort') || 'recent',
    min_sessions: p.get('min_sessions') || '0',
  };
}
export function queryUrl(path, query) { return path + '?' + new URLSearchParams(query).toString(); }
export function createNetworkClient({query, onSnapshot, onError}) {
  let state = {...query}, generation = 0, controller, closed = false;
  let lastVersion = -1, lastSignature = '';
  async function refresh() {
    const ticket = ++generation;
    controller?.abort();
    controller = new AbortController();
    const requested = {...state};
    if(realNetwork() && requested.live==='1')requested.as_of=defaultDate();
    const signature = JSON.stringify(state);
    try {
      const response = await fetch(queryUrl('/network/graph.json', requested), {signal: controller.signal});
      if (!response.ok) throw new Error((await response.json()).error || 'Network unavailable');
      const body = await response.json();
      if (closed || ticket !== generation || body.version < lastVersion) return;
      if (body.version === lastVersion && signature === lastSignature) return;
      lastVersion = body.version;
      lastSignature = signature;
      onSnapshot(body, requested);
    } catch (error) {
      if (error.name !== 'AbortError' && !closed && ticket === generation) onError(error.message);
    }
  }
  const events = new EventSource('/network/events');
  events.addEventListener('update', event => {
    try { if (JSON.parse(event.data).version === lastVersion) return; } catch { /* Refresh unknown payloads. */ }
    refresh();
  });
  events.addEventListener('health',event=>{try{window.dispatchEvent(new CustomEvent('network-health',{detail:JSON.parse(event.data)}));}catch{}});
  events.addEventListener('open', refresh);
  events.onerror = () => { if (!closed) onError('Connection interrupted. Showing the last snapshot; reconnecting automatically.'); };
  refresh();
  return {
    setQuery(patch) { state = {...state, ...patch}; refresh(); }, refresh,
    destroy() { closed = true; controller?.abort(); events.close(); },
  };
}
export function claimMarkup(edge, nodes) {
  const names = new Map(nodes.map(n => [n.id, n.name]));
  return `<div class="claim-item"><strong>${escapeHtml(names.get(edge.source) || edge.source)} · ${escapeHtml(edge.relation)}</strong><small>${escapeHtml(names.get(edge.target) || edge.target)} <span class="claim-state ${edge.status}">${edge.status === 'pending' ? 'Unconfirmed' : edge.active ? 'Current' : 'Historical'}</span></small><small>Effective: ${edge.valid_from ? edge.valid_from.slice(0,10) : 'unknown'}${edge.valid_to ? ' to ' + edge.valid_to.slice(0,10) : ''}<br>Known since ${edge.observed_at.slice(0,10)}</small><button data-evidence="${escapeHtml(edge.id)}">View evidence</button><div data-evidence-body="${escapeHtml(edge.id)}"></div></div>`;
}
export async function showEvidence(container, edge, query) {
  const ids = [...new Set(edge.evidence_ids)], token = Symbol('evidence');
  container.evidenceRequest = token;
  container.innerHTML = '<div class="evidence-progress" aria-live="polite"></div><div class="evidence-sources"></div><button type="button" class="evidence-more">Load more sources</button>';
  const progress = container.querySelector('.evidence-progress'), sources = container.querySelector('.evidence-sources'), more = container.querySelector('.evidence-more');
  const active = () => container.isConnected && container.evidenceRequest === token;
  let offset = 0, busy = false;
  async function loadOne(id, slot) {
    slot.textContent = 'Loading source…';
    try {
      const response = await fetch(queryUrl('/network/evidence/' + encodeURIComponent(id) + '.json', {as_of: query.as_of, ...(query.version ? {version:query.version} : {})}));
      if (!response.ok) throw new Error('Evidence unavailable for this date or revision. Refresh the view if its sources changed.');
      const e = await response.json();
      if (!active()) return;
      slot.innerHTML = `<div class="evidence-meta">${e.data_source==='real'?'Source record':'Fictional'} ${escapeHtml(e.channel)} · ${escapeHtml(e.at.slice(0,10))}</div><blockquote class="evidence-quote">${escapeHtml(e.text)}</blockquote>`;
    } catch {
      if (!active()) return;
      slot.innerHTML = '<p>Source unavailable. Refresh the view if its date or sources changed.</p><button type="button">Retry source</button>';
      slot.querySelector('button').onclick = () => loadOne(id, slot);
    }
  }
  async function loadPage() {
    if (busy || !active()) return;
    busy = true; more.disabled = true;
    const page = ids.slice(offset, offset + 3);
    offset += page.length;
    progress.textContent = `Loading sources ${offset - page.length + 1}–${offset} of ${ids.length}…`;
    await Promise.all(page.map(id => {
      const slot = document.createElement('div'); sources.append(slot);
      return loadOne(id, slot);
    }));
    if (!active()) return;
    progress.textContent = ids.length ? `${offset} of ${ids.length} sources loaded or checked.` : 'No sources supplied.';
    more.hidden = offset >= ids.length; more.disabled = false; busy = false;
  }
  more.onclick = loadPage;
  await loadPage();
}
// Expanded evidence survives a new data revision.
export function bindEvidence(container, snapshot, query, expanded, onSelect = () => {}) {
  container.querySelectorAll('[data-evidence]').forEach(button => {
    const id = button.dataset.evidence;
    async function load() {
      const body = button.nextElementSibling;
      try { await showEvidence(body, snapshot.edges.find(e => e.id === id), {...query,version:snapshot.version}); }
      catch (error) { if (body.isConnected) body.textContent = error.message; }
    }
    button.onclick = () => { expanded.add(id); onSelect(id); load(); };
    if (expanded.has(id)) load();
  });
}
export function preserveFocus(container) {
  const active = document.activeElement, scrollTop = container.scrollTop;
  const key = container.contains(active) && (active.dataset.evidence ? ['data-evidence', active.dataset.evidence]
    : active.dataset.person ? ['data-person', active.dataset.person] : active.id ? ['id', active.id] : null);
  return () => {
    if (key) container.querySelector(`[${key[0]}="${CSS.escape(key[1])}"]`)?.focus({preventScroll: true});
    container.scrollTop = scrollTop;
  };
}
