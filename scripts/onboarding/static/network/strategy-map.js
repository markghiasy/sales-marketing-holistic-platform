import {escapeHtml as esc, queryUrl} from './client.js';

const statusLabels={matching_evidence:'Candidate records',searched_no_match:'No match in searched evidence',not_searched:'Not fully searched',budget_omitted:'Retrieval budget reached',graph_omitted:'Evidence outside this map',search_incomplete:'Search incomplete; coverage unknown'};

// Query candidates only; this component never creates stored relationships.
export function mountStrategyMap(container,initial,query){
  let cy,destroyed=false,selected='',nodes=[],edges=[],records=[],names=new Map();
  const positions=new Map();let laidOut=false;
  container.className='strategy-map';
  container.innerHTML='<h3>Opportunity map</h3><p class="strategy-note"></p><div class="strategy-legend"><span>Solid: recorded relationship</span><span>Dashed: query candidate, not a relationship</span></div><div class="strategy-map-tools"><button type="button" data-fit>Fit map</button></div><div class="strategy-canvas" role="img" aria-label="Opportunity evidence graph. Use the requirement buttons and evidence links below for keyboard access."></div><div class="strategy-requirements" aria-label="Requirements"></div><div class="strategy-records" role="region" aria-label="Candidate evidence" tabindex="0"></div><details class="strategy-connections"><summary>Graph connections</summary><div></div></details>';
  const canvas=container.querySelector('.strategy-canvas');
  if(typeof window.cytoscape==='function'){
    cy=window.cytoscape({container:canvas,elements:[],layout:{name:'preset',fit:false},minZoom:.25,maxZoom:2.5,boxSelectionEnabled:false,
      style:[{selector:'node',style:{'background-color':'#eae4f0','border-color':'#927ca4','border-width':1.5,label:'data(label)',color:'#48414f','font-family':'Segoe UI','font-size':11,'text-wrap':'wrap','text-max-width':100,'text-valign':'bottom','text-margin-y':7,width:28,height:28}},
        {selector:'.requirement',style:{shape:'round-rectangle','background-color':'#e7f1ef','border-color':'#61968b',width:32,height:24}},
        {selector:'.organization',style:{shape:'rectangle','background-color':'#f3e8d3','border-color':'#b28a48',width:27,height:27}},
        {selector:'.project',style:{shape:'diamond','background-color':'#dfefeb','border-color':'#56978c',width:32,height:32}},
        {selector:'edge',style:{width:1.3,'line-color':'#b3a8be','curve-style':'bezier','target-arrow-shape':'none'}},
        {selector:'.candidate',style:{'line-style':'dashed','line-color':'#63978c'}},
        {selector:'.historical',style:{'line-color':'#cbc6d0','line-style':'dotted'}},
        {selector:'.is-highlighted',style:{'border-width':3,'border-color':'#705783','line-color':'#705783',width:3}},
        {selector:'node.is-highlighted',style:{width:32}}]});
    canvas._cy=cy;
    cy.on('tap','node',event=>highlight(event.target.id()));
    cy.on('dragfree','node',event=>positions.set(event.target.id(),{...event.target.position()}));
  }else{canvas.hidden=true;container.querySelector('[data-fit]').hidden=true;}
  function highlight(id){
    selected=id;
    const related=edges.filter(e=>e.source===id||e.target===id),entityIds=new Set([id,...related.flatMap(e=>[e.source,e.target])]);
    const evidenceIds=new Set(related.flatMap(e=>e.evidence_ids||[]));
    container.querySelectorAll('[data-requirement]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.requirement===id)));
    container.querySelectorAll('[data-strategy-record]').forEach((el,i)=>el.classList.toggle('is-highlighted',(records[i].entity_ids||[]).some(x=>entityIds.has(x))||(records[i].evidence_ids||[]).some(x=>evidenceIds.has(x))));
    if(cy){cy.elements().removeClass('is-highlighted');cy.getElementById(id).closedNeighborhood().addClass('is-highlighted');}
  }
  function fit(){if(cy){cy.resize();cy.fit(undefined,38);if(cy.zoom()>1){cy.zoom(1);cy.center();}}}
  function newPosition(id){
    const neighbors=edges.filter(e=>e.source===id||e.target===id).map(e=>e.source===id?e.target:e.source).map(key=>cy.getElementById(key)).filter(node=>node.length);
    const anchors=neighbors.length?neighbors:[...cy.nodes()];
    const center=anchors.length?anchors.reduce((p,n)=>({x:p.x+n.position('x')/anchors.length,y:p.y+n.position('y')/anchors.length}),{x:0,y:0}):{x:0,y:0};
    const phase=[...id].reduce((seed,c)=>(seed*31+c.charCodeAt(0))>>>0,7)/4294967296*Math.PI*2;
    let point=center;
    for(let attempt=0;attempt<48;attempt++){
      const angle=phase+attempt*2.399963, radius=95+Math.floor(attempt/8)*45;
      point={x:center.x+Math.cos(angle)*radius,y:center.y+Math.sin(angle)*radius};
      if(cy.nodes().every(n=>Math.abs(n.position('x')-point.x)>95||Math.abs(n.position('y')-point.y)>65))break;
    }
    return point;
  }
  function update(data){
    if(destroyed)return;
    const requirements=(data.requirements||[]).slice(0,12).map(r=>({...r,id:r.id.startsWith('requirement:')?r.id:'requirement:'+r.id}));
    records=(data.records||[]).slice(0,30);nodes=[...(data.nodes||[])].slice(0,28);
    requirements.forEach(r=>{if(!nodes.some(n=>n.id===r.id))nodes.push({id:r.id,name:r.label,kind:'requirement'});});
    const ids=new Set(nodes.map(n=>n.id));names=new Map(nodes.map(n=>[n.id,n.name]));
    edges=(data.edges||[]).filter(e=>ids.has(e.source)&&ids.has(e.target)&&['candidate','relationship'].includes(e.kind)&&(e.kind!=='relationship'||!e.status||e.status==='confirmed')).slice(0,200);
    const sources=new Map((data.evidence||[]).map(s=>[s.id,s]));
    const entityLink=id=>`<a href="${esc(queryUrl('/network',{focus:id,expand:id,scopes:'direct,explicit,project,organization',as_of:query.as_of,mode:query.mode}))}">${esc(names.get(id)||id)}</a>`;
    const expanded=new Set([...container.querySelectorAll('[data-strategy-record]')].filter(el=>el.querySelector('details')?.open).map(el=>el.dataset.strategyRecord));
    const focused=document.activeElement?.dataset?.requirement;
    const recordFocus=document.activeElement?.closest('[data-strategy-record]')?.dataset.strategyRecord;
    const focusHref=document.activeElement?.getAttribute('href'),focusTag=document.activeElement?.tagName;
    container.querySelector('.strategy-note').textContent=data.note||'Candidate evidence needs validation. Connections do not establish buying authority or introduction willingness.';
    container.querySelector('.strategy-requirements').innerHTML=requirements.map(r=>`<button type="button" data-requirement="${esc(r.id)}" aria-pressed="false">${r.origin==='suggested'?'Suggested: ':''}${esc(r.label)}<small>${esc(statusLabels[r.status]||r.status||'Not fully searched')}${r.omitted_evidence_count?' · '+esc(r.omitted_evidence_count)+' sources outside this map':''}</small></button>`).join('');
    container.querySelector('.strategy-records').innerHTML=records.map(r=>`<section class="strategy-record" data-strategy-record="${esc(r.id)}"><strong>${esc(r.label)}</strong><div class="agent-entity-links">${(r.entity_ids||[]).filter(id=>!id.startsWith('requirement:')).map(entityLink).join('')}</div>${r.quote?`<blockquote>${esc(r.quote)}</blockquote>`:''}<details${expanded.has(r.id)?' open':''}><summary>View ${(r.evidence_ids||[]).length} source records</summary>${(r.evidence_ids||[]).map(id=>{const s=sources.get(id);return s?`<p><a href="${esc(queryUrl('/network/evidence/'+encodeURIComponent(id)+'.json',{as_of:query.as_of}))}" target="_blank" rel="noopener">${esc(s.channel)} · ${esc(s.at?.slice(0,10))}</a></p><blockquote>${esc(s.text)}</blockquote>`:'<p>Source is outside this answer.</p>';}).join('')}</details></section>`).join('')||'<p class="strategy-note">No eligible records for these requirements at this date.</p>';
    container.querySelector('.strategy-connections summary').textContent=`Graph connections (${edges.length})`;
    container.querySelector('.strategy-connections>div').innerHTML=edges.map(e=>`<p><strong>${esc(e.kind==='candidate'?'Query candidate':e.active===false?'Historical relationship':'Recorded relationship')}</strong>: ${esc(names.get(e.source))} — ${esc(e.label)} — ${esc(names.get(e.target))}</p>`).join('');
    container.querySelectorAll('[data-requirement]').forEach(b=>{b.onclick=()=>highlight(b.dataset.requirement);if(b.dataset.requirement===focused)b.focus({preventScroll:true});});
    if(recordFocus){
      const record=[...container.querySelectorAll('[data-strategy-record]')].find(el=>el.dataset.strategyRecord===recordFocus);
      const target=focusTag==='SUMMARY'?record?.querySelector('summary'):[...(record?.querySelectorAll('a')||[])].find(a=>a.getAttribute('href')===focusHref);
      target?.focus({preventScroll:true});
    }
    if(cy){
      const allIds=new Set([...ids,...edges.map(e=>e.id)]);
      cy.batch(()=>{
        cy.elements().filter(el=>!allIds.has(el.id())).remove();
        for(const [index,n] of nodes.entries()){
          const existing=cy.getElementById(n.id);
          if(existing.length){existing.data({...n,label:n.name});continue;}
          if(!positions.has(n.id)){
            const angle=index/Math.max(nodes.length,1)*Math.PI*2;
            positions.set(n.id,laidOut?newPosition(n.id):{x:180+Math.cos(angle)*130,y:180+Math.sin(angle)*130});
          }
          cy.add({data:{...n,label:n.name},classes:n.kind||'person',position:positions.get(n.id)});
        }
        for(const e of edges){const existing=cy.getElementById(e.id);if(existing.length)existing.data(e);else cy.add({data:e,classes:e.kind+(e.active===false?' historical':'')});}
      });
      if(!laidOut&&nodes.length){
        cy.layout({name:'cose',randomize:false,animate:false,fit:false,nodeRepulsion:9000,idealEdgeLength:105,nodeOverlap:28,componentSpacing:100,gravity:.4,numIter:300}).run();
        cy.nodes().forEach(node=>positions.set(node.id(),{...node.position()}));
        fit();laidOut=true;
      }
    }
    if(selected)highlight(selected);
  }
  container.querySelector('[data-fit]').onclick=fit;
  let previousWidth=canvas.clientWidth;
  const observer=new ResizeObserver(()=>{if(!destroyed){cy?.resize();if(canvas.clientWidth!==previousWidth){previousWidth=canvas.clientWidth;fit();}}});observer.observe(canvas);
  update(initial);
  return {update,destroy(){destroyed=true;observer.disconnect();cy?.destroy();delete canvas._cy;}};
}
