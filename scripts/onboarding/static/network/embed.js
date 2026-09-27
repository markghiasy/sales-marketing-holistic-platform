import {mountGraph} from './graph.js';
import {createNetworkClient,readQuery,queryUrl,escapeHtml as esc,claimMarkup,showEvidence} from './client.js';

export function mountEmbedded(container,personKey){
  const query={...readQuery(),focus:personKey,view:'compact'};
  let snapshot,selectedClaim='';
  container.className='network-embed';
  container.innerHTML=`<div class="embed-toolbar"><strong>Connections in context</strong><a class="open-network" href="${esc(queryUrl('/network',query))}">Open full network</a></div><div class="embed-canvas" aria-label="Contact relationship graph"></div><div class="embed-inspector"></div><div class="embed-status" role="status">Loading supported connections…</div>`;
  const inspector=container.querySelector('.embed-inspector'),status=container.querySelector('.embed-status');
  function inspect(){if(!snapshot)return;const edges=selectedClaim?snapshot.edges.filter(e=>e.id===selectedClaim):snapshot.edges.filter(e=>e.source===personKey||e.target===personKey).slice(0,3);inspector.innerHTML=edges.map(e=>claimMarkup(e,snapshot.nodes)).join('');inspector.querySelectorAll('[data-evidence]').forEach(button=>button.onclick=async()=>{const edge=snapshot.edges.find(e=>e.id===button.dataset.evidence);try{await showEvidence(button.nextElementSibling,edge,query);}catch(error){button.nextElementSibling.textContent=error.message;}});}
  const graph=mountGraph(container.querySelector('.embed-canvas'),{mode:'compact',onNodeSelect(id){const node=snapshot.nodes.find(n=>n.id===id);selectedClaim='';inspector.innerHTML=`<h3>${esc(node.name)}</h3><p>${esc(node.role)}</p>${node.kind==='person'?`<a href="${esc(queryUrl('/inbox',{...query,focus:id}))}">Open conversation</a>`:''}`;},onEdgeSelect(id){selectedClaim=id;inspect();}});
  const client=createNetworkClient({query,onSnapshot(data){snapshot=data;graph.setSnapshot(data);inspect();status.textContent=`Synthetic demo · ${data.nodes.length} entities · ${data.edges.length} connections${data.truncated?' · '+data.omitted_counts.nodes+' more in full network':''}`;container.querySelector('.open-network').href=queryUrl('/network',{...query,view:'explorer',...(selectedClaim?{claim:selectedClaim}:{})});},onError:message=>status.textContent=message});
  return {destroy(){client.destroy();graph.destroy();}};
}
