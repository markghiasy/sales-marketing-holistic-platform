export const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const initials = name => name.split(' ').map(s => s[0]).slice(0, 2).join('');
export function readQuery() {
  const p = new URLSearchParams(location.search);
  return {
    focus: p.get('focus') || 'person:owner', origin: p.get('origin') || '',
    as_of: p.get('as_of') || '2026-09-27T12:00:00Z', search: p.get('search') || '',
    function: p.get('function') || '', organization: p.get('organization') || '',
    project: p.get('project') || '', mode: p.get('mode') || 'current',
    include_pending: p.get('include_pending') || 'false', expand: p.get('expand') || '',
    depth: p.get('depth') || '2', min_activity: p.get('min_activity') || '0',
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
    const requested = {...state}, signature = JSON.stringify(requested);
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
  const results = await Promise.all(edge.evidence_ids.map(async id => {
    const response = await fetch(queryUrl('/network/evidence/' + encodeURIComponent(id) + '.json', {as_of: query.as_of}));
    if (!response.ok) throw new Error('Evidence unavailable for this date.');
    return response.json();
  }));
  if (!container.isConnected) return;
  container.innerHTML = results.map(e => `<div class="evidence-meta">Fictional ${escapeHtml(e.channel)} message · ${escapeHtml(e.at.slice(0,10))}</div><blockquote class="evidence-quote">${escapeHtml(e.text)}</blockquote>`).join('');
}
// Expanded evidence survives a new data revision.
export function bindEvidence(container, snapshot, query, expanded, onSelect = () => {}) {
  container.querySelectorAll('[data-evidence]').forEach(button => {
    const id = button.dataset.evidence;
    async function load() {
      const body = button.nextElementSibling;
      try { await showEvidence(body, snapshot.edges.find(e => e.id === id), query); }
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
