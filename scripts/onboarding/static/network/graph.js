export function mountGraph(container,{mode='explorer',onNodeSelect=()=>{},onEdgeSelect=()=>{}}={}) {
  const compact=mode==='compact';
  const cy=window.cytoscape({container,elements:[],minZoom:.25,maxZoom:2.5,wheelSensitivity:.2,style:[
    {selector:'node',style:{'label':'data(name)','font-family':'Segoe UI','font-size':compact?12:11,'text-valign':'bottom','text-margin-y':8,'text-wrap':'wrap','text-max-width':105,'background-color':'#197c80','color':'#314a5c','width':compact?25:23,'height':compact?25:23,'border-width':3,'border-color':'#fff','text-background-color':'#fcfdfe','text-background-opacity':.9,'text-background-padding':3}},
    {selector:'node[kind="organization"]',style:{'shape':'round-rectangle','background-color':'#9b762d','width':32,'height':28,'font-weight':600}},
    {selector:'node[kind="project"]',style:{'shape':'diamond','background-color':'#7563a9','width':36,'height':36,'font-weight':600}},
    {selector:'node.owner',style:{'background-color':'#254b75','width':42,'height':42,'font-size':13,'font-weight':700}},
    {selector:'node.focus',style:{'border-color':'#80b9c6','border-width':6}},
    {selector:'edge',style:{'width':1.3,'line-color':'#c8d7df','curve-style':'bezier','target-arrow-shape':'triangle','target-arrow-color':'#c8d7df','arrow-scale':.6,'font-size':10,'color':'#476175','text-background-color':'#fff','text-background-opacity':1,'text-background-padding':3,'text-rotation':'autorotate','label':''}},
    {selector:'edge[status="pending"]',style:{'line-style':'dashed','line-color':'#b79756','target-arrow-color':'#b79756'}},
    {selector:'edge[active = false]',style:{'line-style':'dotted','opacity':.6}},
    {selector:'.dim',style:{'opacity':.18}},
    {selector:'edge.highlight',style:{'line-color':'#378996','target-arrow-color':'#378996','width':2.3,'label':'data(relation)'}},
    {selector:'node:selected',style:{'border-color':'#294f75','border-width':5}},
    {selector:'edge:selected',style:{'line-color':'#254b75','target-arrow-color':'#254b75','width':3,'label':'data(relation)'}}
  ]});
  let signature='';
  function highlight(element){cy.elements().removeClass('dim highlight');const neighborhood=element.isNode()?element.closedNeighborhood():element.union(element.connectedNodes());cy.elements().difference(neighborhood).addClass('dim');neighborhood.edges().addClass('highlight');}
  cy.on('tap','node',event=>{highlight(event.target);onNodeSelect(event.target.id());});
  cy.on('tap','edge',event=>{highlight(event.target);onEdgeSelect(event.target.id());});
  cy.on('tap',event=>{if(event.target===cy)cy.elements().removeClass('dim highlight');});
  const observer=new ResizeObserver(()=>cy.resize());observer.observe(container);
  function readableLabels(){
    const zoom=cy.zoom();
    cy.style().selector('node').style({'font-size':12/zoom,'text-max-width':105/zoom,'text-margin-y':7/zoom})
      .selector('node.owner').style({'font-size':14/zoom})
      .selector('edge').style({'line-color':'#b4c8d4','target-arrow-color':'#b4c8d4','width':1.4/zoom,'font-size':11/zoom}).update();
  }
  cy.on('zoom',readableLabels);
  return {
    setSnapshot(snapshot){
      const next=snapshot.nodes.map(n=>n.id).join('|')+';'+snapshot.edges.map(e=>e.id).join('|');
      const positions={};cy.nodes().forEach(n=>positions[n.id()]={...n.position()});
      const viewport={zoom:cy.zoom(),pan:{...cy.pan()}};
      cy.batch(()=>{cy.elements().remove();cy.add(snapshot.nodes.map(n=>({data:n,classes:[n.id===snapshot.owner_id?'owner':'',n.id===snapshot.focus_id?'focus':''].join(' '),position:positions[n.id]})));cy.add(snapshot.edges.map(e=>({data:e})));});
      if(next!==signature){
        if(!compact && snapshot.nodes.length>12){
          const groups=['north','atlas','uni'],counts={north:0,atlas:0,uni:0};
          cy.nodes().positions(n=>{
            if(n.id()===snapshot.owner_id)return{x:330,y:0};
            if(n.data('kind')==='project')return{x:n.id().endsWith('harbour')?70:590,y:0};
            if(n.data('kind')==='organization')return{x:70+groups.indexOf(n.id().split(':')[1])*260,y:100};
            const cluster=n.data('cluster')||'north',i=counts[cluster]++,col=groups.indexOf(cluster);
            return{x:col*260+(i%2)*130,y:200+Math.floor(i/2)*90};
          });
        }else{
          cy.layout({name:'concentric',animate:false,concentric:n=>n.id()===snapshot.focus_id?10:1,levelWidth:()=>2,minNodeSpacing:55,padding:35,startAngle:Math.PI*1.5}).run();
        }
        cy.fit(undefined,compact?35:45);
        if(cy.zoom()>1.15)cy.zoom({level:1.15,renderedPosition:{x:container.clientWidth/2,y:container.clientHeight/2}});
      }else{cy.nodes().positions(n=>positions[n.id()]);cy.viewport(viewport);}
      signature=next;
      readableLabels();
    },
    select(id){const el=cy.getElementById(id);cy.elements().unselect();if(el.length){el.select();highlight(el);}},
    fit(){cy.fit(undefined,35);},
    destroy(){observer.disconnect();cy.destroy();}
  };
}
