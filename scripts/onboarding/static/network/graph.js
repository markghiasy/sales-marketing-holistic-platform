// Both hosts share the same graph, palette, layout and interaction rules.
export function mountGraph(container, {mode = 'explorer', onNodeSelect = () => {}, onEdgeSelect = () => {}} = {}) {
  const compact = mode === 'compact';
  const theme = getComputedStyle(container);
  const color = name => theme.getPropertyValue('--net-' + name).trim();
  const cy = window.cytoscape({
    container, elements: [], minZoom: .2, maxZoom: 3.5,
    style: [
      {selector: 'node', style: {
        'label': 'data(name)', 'font-family': 'Segoe UI', 'font-size': 11,
        'color': color('muted'), 'text-opacity': 0, 'text-valign': 'bottom',
        'text-margin-y': 9, 'text-wrap': 'wrap', 'text-max-width': 120,
        'background-color': color('teal'), 'width': 9, 'height': 9,
        'border-width': 1, 'border-color': '#ffffff', 'border-opacity': .8,
        'overlay-opacity': 0, 'underlay-color': color('teal'), 'underlay-opacity': .055,
        'underlay-padding': 5, 'underlay-shape': 'ellipse',
        'text-background-color': color('canvas'), 'text-background-opacity': .85, 'text-background-padding': 3,
      }},
      {selector: 'node[kind="organization"]', style: {
        'shape': 'round-rectangle', 'background-color': color('gold'), 'border-color': '#ffffff',
        'underlay-color': color('gold'), 'width': 14, 'height': 14,
        'text-opacity': 1, 'color': color('org-label'),
      }},
      {selector: 'node[kind="project"]', style: {
        'shape': 'diamond', 'background-color': color('violet'), 'border-color': '#ffffff',
        'underlay-color': color('violet'), 'width': 17, 'height': 17,
        'text-opacity': 1, 'color': color('project-label'),
      }},
      {selector: 'node.owner', style: {
        'background-color': color('owner'), 'border-color': '#ffffff', 'width': 19, 'height': 19,
        'text-opacity': 1, 'font-weight': 600, 'color': color('owner'),
        'underlay-opacity': .08, 'underlay-padding': 13,
      }},
      {selector: 'node.focus', style: {'text-opacity': 1}},
      {selector: 'node.show-label', style: {'text-opacity': 1}},
      {selector: 'edge', style: {
        'width': .8, 'line-color': color('edge'), 'opacity': .6, 'curve-style': 'bezier',
        'control-point-step-size': 22, 'target-arrow-shape': 'none',
        'font-family': 'Segoe UI', 'font-size': 10, 'color': color('blue'),
        'text-background-color': color('canvas'), 'text-background-opacity': .95,
        'text-background-padding': 4, 'text-rotation': 'autorotate', 'label': '',
        'overlay-opacity': 0,
      }},
      {selector: 'edge[status="pending"]', style: {'line-style': 'dashed', 'line-color': color('gold')}},
      {selector: 'edge.historical', style: {'line-style': 'dotted', 'opacity': .25}},
      {selector: 'node.dim', style: {'opacity': .35}},
      {selector: 'edge.dim', style: {'opacity': .1}},
      {selector: 'node.neighbor', style: {'text-opacity': 1, 'color': color('ink')}},
      {selector: 'edge.highlight', style: {'line-color': color('teal'), 'opacity': .8, 'width': 1.2}},
      {selector: 'node.hovered, node:selected', style: {
        'text-opacity': 1, 'color': color('ink'), 'border-color': color('owner'),
        'border-width': 2, 'underlay-opacity': .15, 'underlay-padding': 9,
      }},
      {selector: 'edge.hovered, edge:selected', style: {
        'line-color': color('owner'), 'opacity': 1, 'width': 1.7, 'label': 'data(relation)',
        'target-arrow-shape': 'triangle', 'target-arrow-color': color('owner'), 'arrow-scale': .6,
      }},
    ],
  });
  let signature = '', selectedId = '', labelTier = '';
  function clearHighlight() { cy.elements().removeClass('dim highlight neighbor'); }
  function highlight(element) {
    clearHighlight();
    const neighborhood = element.isNode() ? element.closedNeighborhood() : element.union(element.connectedNodes());
    cy.elements().difference(neighborhood).addClass('dim');
    neighborhood.edges().addClass('highlight');
    neighborhood.nodes().addClass('neighbor');
  }
  function select(id) {
    selectedId = id;
    cy.elements().unselect();
    const element = cy.getElementById(id);
    if (element.length) { element.select(); highlight(element); }
    else clearHighlight();
  }
  cy.on('tap', 'node', event => { select(event.target.id()); onNodeSelect(event.target.id()); });
  cy.on('tap', 'edge', event => { select(event.target.id()); onEdgeSelect(event.target.id()); });
  cy.on('tap', event => { if (event.target === cy) { selectedId = ''; cy.elements().unselect(); clearHighlight(); } });
  cy.on('mouseover', 'node, edge', event => {
    container.style.cursor = 'pointer';
    event.target.addClass('hovered');
    if (!selectedId) highlight(event.target);
  });
  cy.on('mouseout', 'node, edge', event => {
    container.style.cursor = 'grab';
    event.target.removeClass('hovered');
    if (!selectedId) clearHighlight();
  });
  function readableLabels() {
    const zoom = cy.zoom();
    const tier = compact || cy.nodes().length <= 10 || zoom > 1.45 ? 'all' : 'anchors';
    if (tier !== labelTier) { cy.nodes().toggleClass('show-label', tier === 'all'); labelTier = tier; }
    cy.style().selector('node').style({'font-size': 11 / zoom, 'text-max-width': 120 / zoom, 'text-margin-y': 9 / zoom})
      .selector('edge').style({'font-size': 10 / zoom}).update();
  }
  cy.on('zoom', readableLabels);
  let width = container.clientWidth, height = container.clientHeight;
  const observer = new ResizeObserver(() => {
    const nextWidth = container.clientWidth, nextHeight = container.clientHeight;
    const pan = cy.pan();
    cy.resize();
    cy.pan({x: pan.x + (nextWidth - width) / 2, y: pan.y + (nextHeight - height) / 2});
    width = nextWidth; height = nextHeight;
  });
  observer.observe(container);
  const fitPadding = () => compact ? 38 : Math.min(65, container.clientWidth * .08);

  function arrange() {
    // Seed the force layout with separated positions instead of columns or rings.
    cy.nodes().forEach((node, i) => {
      const angle = i * 2.399963229728653;
      const radius = 38 * Math.sqrt(i + 1);
      node.position({x: Math.cos(angle) * radius, y: Math.sin(angle) * radius});
    });
    cy.layout({
      name: 'cose', animate: false, randomize: false, fit: false,
      nodeRepulsion: () => 18000, idealEdgeLength: () => compact ? 85 : 100,
      edgeElasticity: () => 110, nodeOverlap: 18, gravity: .18,
      numIter: 1200, initialTemp: 120, coolingFactor: .97, minTemp: .5,
      componentSpacing: 100,
    }).run();
    cy.fit(undefined, fitPadding());
    if (cy.zoom() > (compact ? 1.2 : 1.35)) {
      cy.zoom(compact ? 1.2 : 1.35);
      cy.center();
    }
  }
  return {
    setSnapshot(snapshot) {
      const next = snapshot.nodes.map(n => n.id).join('|') + ';' + snapshot.edges.map(e => e.id).join('|');
      const positions = {};
      cy.nodes().forEach(n => positions[n.id()] = {...n.position()});
      const viewport = {zoom: cy.zoom(), pan: {...cy.pan()}};
      cy.batch(() => {
        cy.elements().remove();
        cy.add(snapshot.nodes.map(n => ({data: n, classes: [n.id === snapshot.owner_id ? 'owner' : '', n.id === snapshot.focus_id ? 'focus' : ''].join(' '), position: positions[n.id]})));
        cy.add(snapshot.edges.map(e => ({data: e, classes: e.active ? '' : 'historical'})));
      });
      labelTier = '';
      if (next !== signature) arrange();
      else { cy.nodes().positions(n => positions[n.id()]); cy.viewport(viewport); }
      signature = next;
      readableLabels();
      if (selectedId && cy.getElementById(selectedId).length) select(selectedId);
      else selectedId = '';
    },
    select,
    fit() { cy.fit(undefined, fitPadding()); },
    destroy() { observer.disconnect(); cy.destroy(); },
  };
}
