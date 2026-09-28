import {escapeHtml as esc, queryUrl} from './client.js';

const statusLabels = {matching_evidence:'Candidate records', searched_no_match:'Evidence gap', not_searched:'Not fully searched', budget_omitted:'Evidence outside this answer', graph_omitted:'Evidence outside this map'};

// This view only projects the answer's bounded evidence pack. It never writes relationships.
export function mountStrategyMap(container, data, query) {
  const requirements=(data.requirements||[]).slice(0,12).map(r=>({...r,id:r.id.startsWith('requirement:')?r.id:'requirement:'+r.id})), records=(data.records||[]).slice(0,30);
  const nodes=[...(data.nodes||[])].slice(0,28);
  requirements.forEach(r=>{if(!nodes.some(n=>n.id===r.id))nodes.push({id:r.id,name:r.label,kind:'requirement'});});
  const ids=new Set(nodes.map(n=>n.id)), names=new Map(nodes.map(n=>[n.id,n.name]));
  const edges=(data.edges||[]).filter(e=>ids.has(e.source)&&ids.has(e.target)&&['candidate','relationship'].includes(e.kind)&&(e.kind!=='relationship'||!e.status||e.status==='confirmed')).slice(0,200);
  const sources=new Map((data.evidence||[]).map(s=>[s.id,s]));
  const entityLink=id=>`<a href="${esc(queryUrl('/network',{focus:id,expand:id,depth:2,as_of:query.as_of,mode:query.mode}))}">${esc(names.get(id)||id)}</a>`;
  container.className='strategy-map';
  container.innerHTML=`<h3>Opportunity map</h3><p class="strategy-note">${esc(data.note||'Candidate evidence needs validation. Connections do not establish buying authority or introduction willingness.')}</p>
    <div class="strategy-legend"><span>Solid: recorded relationship</span><span>Dashed: query candidate, not a relationship</span></div>
    <div class="strategy-canvas" role="img" aria-label="Opportunity evidence graph. Use the requirement buttons and evidence links below for keyboard access."></div>
    <div class="strategy-requirements" aria-label="Requirements">${requirements.map(r=>`<button type="button" data-requirement="${esc(r.id)}" aria-pressed="false">${r.origin==='suggested'?'Suggested: ':''}${esc(r.label)}<small>${esc(statusLabels[r.status]||r.status)}${r.omitted_evidence_count?' · '+esc(r.omitted_evidence_count)+' sources outside this map':''}</small></button>`).join('')}</div>
    <div class="strategy-records">${records.map(r=>`<section class="strategy-record" data-strategy-record="${esc(r.id)}"><strong>${esc(r.label)}</strong><div class="agent-entity-links">${(r.entity_ids||[]).filter(id=>!id.startsWith('requirement:')).map(entityLink).join('')}</div>${r.quote?`<blockquote>${esc(r.quote)}</blockquote>`:''}<details><summary>View ${(r.evidence_ids||[]).length} source record${r.evidence_ids?.length===1?'':'s'}</summary>${(r.evidence_ids||[]).map(id=>{const s=sources.get(id);return s?`<p><a href="${esc(queryUrl('/network/evidence/'+encodeURIComponent(id)+'.json',{as_of:query.as_of}))}" target="_blank" rel="noopener">${esc(s.channel)} · ${esc(s.at?.slice(0,10))}</a></p><blockquote>${esc(s.text)}</blockquote>`:'<p>Source is outside this answer.</p>';}).join('')}</details></section>`).join('')||'<p class="strategy-note">No eligible records for these requirements at this date.</p>'}</div>
    <details class="strategy-connections"><summary>Graph connections (${edges.length})</summary>${edges.map(e=>`<p><strong>${esc(e.kind==='candidate'?'Query candidate':e.active===false?'Historical relationship':'Recorded relationship')}</strong>: ${esc(names.get(e.source))} — ${esc(e.label)} — ${esc(names.get(e.target))}</p>`).join('')}</details>`;
  let cy, timer, resizeObserver, destroyed=false;
  function highlight(id) {
    const related=edges.filter(e=>e.source===id||e.target===id);
    const entityIds=new Set([id,...related.flatMap(e=>[e.source,e.target])]);
    const evidenceIds=new Set(related.flatMap(e=>e.evidence_ids||[]));
    container.querySelectorAll('[data-requirement]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.requirement===id)));
    container.querySelectorAll('[data-strategy-record]').forEach((el,i)=>el.classList.toggle('is-highlighted',(records[i].entity_ids||[]).some(x=>entityIds.has(x))||(records[i].evidence_ids||[]).some(x=>evidenceIds.has(x))));
    if(cy){cy.elements().removeClass('is-highlighted');cy.getElementById(id).closedNeighborhood().addClass('is-highlighted');}
  }
  container.querySelectorAll('[data-requirement]').forEach(b=>b.onclick=()=>highlight(b.dataset.requirement));
  const canvas=container.querySelector('.strategy-canvas');
  if(typeof window.cytoscape==='function'&&nodes.length){
    const reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    cy=window.cytoscape({container:canvas,elements:[...nodes.map(n=>({data:{...n,label:n.name},classes:n.kind==='requirement'?'requirement':''})),...edges.map(e=>({data:e,classes:e.kind+(e.active===false?' historical':'')}))],
      layout:{name:'preset',fit:false},minZoom:1,maxZoom:1,userZoomingEnabled:false,userPanningEnabled:false,boxSelectionEnabled:false,
      style:[{selector:'node',style:{'background-color':'#eae4f0','border-color':'#927ca4','border-width':1.5,label:'data(label)',color:'#48414f','font-family':'Segoe UI','font-size':11,'text-wrap':'wrap','text-max-width':98,'text-valign':'bottom','text-margin-y':7,width:28,height:28}},
        {selector:'.requirement',style:{shape:'round-rectangle','background-color':'#e7f1ef','border-color':'#61968b',width:32,height:24}},
        {selector:'edge',style:{width:1.3,'line-color':'#b3a8be','curve-style':'bezier','target-arrow-shape':'none',opacity:reduced?1:0}},
        {selector:'.candidate',style:{'line-style':'dashed','line-color':'#63978c'}},
        {selector:'.historical',style:{'line-color':'#cbc6d0','line-style':'dotted'}},
        {selector:'.is-highlighted',style:{'border-width':3,'border-color':'#705783','line-color':'#705783',width:3}},
        {selector:'node.is-highlighted',style:{width:32}}]});
    cy.on('tap','node',event=>highlight(event.target.id()));
    function fitMap(){
      if(destroyed)return;
      const width=canvas.clientWidth, columns=width<400?2:nodes.length>12?4:3;
      const rows=Math.ceil(nodes.length/columns), height=Math.max(245,Math.min(560,rows*84+25));
      canvas.style.height=height+'px';cy.resize();
      cy.nodes().forEach((node,i)=>node.position({x:(i%columns+.5)*width/columns,y:(Math.floor(i/columns)+.4)*height/rows}));
      cy.style().selector('node').style('text-max-width',Math.min(110,width/columns-16)).update();
    }
    fitMap();
    resizeObserver=new ResizeObserver(fitMap);
    resizeObserver.observe(canvas);
    // Evidence is already received; motion only reveals that result, never simulated searching.
    if(!reduced)timer=setTimeout(()=>{if(!destroyed)cy.edges().animate({style:{opacity:1}},{duration:350});},180);
  }else{canvas.hidden=true;}
  return {destroy(){destroyed=true;clearTimeout(timer);resizeObserver?.disconnect();cy?.destroy();}};
}
