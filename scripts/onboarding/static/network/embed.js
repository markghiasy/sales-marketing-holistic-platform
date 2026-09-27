import {mountGraph} from './graph.js';
import {createNetworkClient, readQuery, queryUrl, escapeHtml as esc, claimMarkup, bindEvidence, preserveFocus} from './client.js';

export function mountEmbedded(container, personKey) {
  const query = {...readQuery(), focus: personKey, origin: personKey, view: 'compact'};
  let snapshot, selectedId = personKey;
  let selectedClaim = new URLSearchParams(location.search).get('claim') || '';
  const expanded = new Set(selectedClaim ? [selectedClaim] : []);
  container.className = 'network-embed';
  container.innerHTML = `<div class="embed-toolbar"><strong>Connections in context</strong><a class="open-network">Open full network</a></div><div class="embed-canvas" aria-label="Contact relationship graph"></div><label>Inspect entity <select id="embed-entity" aria-label="Inspect entity"></select></label><div class="embed-inspector"></div><div class="embed-status" role="status">Loading supported connections…</div>`;
  const inspector = container.querySelector('.embed-inspector');
  const status = container.querySelector('.embed-status');
  const select = container.querySelector('#embed-entity');
  function syncLink() {
    container.querySelector('.open-network').href = queryUrl('/network', {...query, view: 'explorer', ...(selectedClaim ? {claim: selectedClaim} : {})});
  }
  function chooseClaim(id) { selectedClaim = id; graph.select(id); syncLink(); }
  function inspect() {
    if (!snapshot) return;
    const restore = preserveFocus(inspector);
    const node = snapshot.nodes.find(n => n.id === selectedId);
    inspector.innerHTML = `${node ? `<h3>${esc(node.name)}</h3><p>${esc(node.role)}</p>` : ''}${snapshot.edges.map(e => claimMarkup(e, snapshot.nodes)).join('')}`;
    bindEvidence(inspector, snapshot, query, expanded, chooseClaim);
    restore();
  }
  function chooseNode(id) { selectedId = id; selectedClaim = ''; select.value = id; graph.select(id); inspect(); syncLink(); }
  const graph = mountGraph(container.querySelector('.embed-canvas'), {
    mode: 'compact', onNodeSelect: chooseNode,
    onEdgeSelect(id) { chooseClaim(id); expanded.add(id); inspect(); },
  });
  select.onchange = () => chooseNode(select.value);
  syncLink();
  const client = createNetworkClient({query, onSnapshot(data) {
    snapshot = data;
    if (selectedClaim && !data.edges.some(e => e.id === selectedClaim)) selectedClaim = '';
    if (!data.nodes.some(n => n.id === selectedId)) selectedId = personKey;
    graph.setSnapshot(data);
    if (selectedClaim) graph.select(selectedClaim);
    else graph.select(selectedId);
    select.innerHTML = data.nodes.map(n => `<option value="${esc(n.id)}">${esc(n.name)}</option>`).join('');
    select.value = selectedId;
    inspect(); syncLink();
    status.textContent = `Synthetic demo · ${data.nodes.length} entities · ${data.edges.length} connections${data.truncated ? ' · ' + data.omitted_counts.nodes + ' more in full network' : ''}`;
  }, onError: message => status.textContent = message});
  return {destroy() { client.destroy(); graph.destroy(); }};
}
