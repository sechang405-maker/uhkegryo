import test from 'node:test';
import assert from 'node:assert/strict';
import { ACTIVE_TERMS, HOME_TERMS } from '../lib/home-catalog.mjs';
import { buildTermGraph, buildExpandedTermGraph, projectNode, projectGraph, resolveGraphProjection, INITIAL_VIEW, toggleTerm, toggleExpanded, appendTerms } from '../lib/term-graph.mjs';

test('graph retains each example once and connects only its actual category', () => {
 const graph = buildTermGraph([...HOME_TERMS, HOME_TERMS[0], {role:'invented',term_id:'bad',label_ko:'bad'}]);
 assert.equal(graph.nodes.filter(n=>n.term).length,36);
 assert.equal(graph.nodes.length,40);
 assert.equal(graph.edges.length,36);
 for(const edge of graph.edges) {
  const target=graph.nodes.find(n=>n.id===edge.target);
  assert.equal(edge.source,`category:${target.term.role}`);
 }
 assert.ok(new Set(graph.nodes.map(n=>n.z)).size>3);
});
test('projection rotates real depth and keeps extreme zoom finite', () => {
 const node={x:100,y:30,z:180};
 const front=projectNode(node,{yaw:0,pitch:0,zoom:1});
 const side=projectNode(node,{yaw:Math.PI/2,pitch:0,zoom:1});
 assert.notEqual(front.x,side.x);
 assert.notEqual(front.depth,side.depth);
 for(const zoom of [-100,100]) for(const value of Object.values(projectNode(node,{yaw:0,pitch:0,zoom}))) assert.ok(Number.isFinite(value));
});
test('multiple terms in the same category remain independent and toggle by ID', () => {
 let selected=toggleTerm([],HOME_TERMS[0].term_id);
 selected=toggleTerm(selected,HOME_TERMS[1].term_id);
 assert.equal(selected.length,2);
 assert.deepEqual(toggleTerm(selected,HOME_TERMS[0].term_id),[HOME_TERMS[1].term_id]);
});
test('adding terms preserves the draft, deduplicates labels and respects the input limit', () => {
 const text=appendTerms('기존 초안',HOME_TERMS.slice(0,2));
 assert.ok(text.startsWith('기존 초안'));
 assert.ok(text.includes(HOME_TERMS[1].label_ko));
 assert.equal(appendTerms(text,HOME_TERMS.slice(0,2)),text);
 assert.equal(appendTerms('가'.repeat(499),HOME_TERMS.slice(0,2)),null);
 assert.equal(appendTerms('🙂'.repeat(490),HOME_TERMS.slice(0,1))?.startsWith('🙂'),true);
});

test('all rendered anchors equal their perspective projection without grid or screen repacking',()=>{
 const graph=buildTermGraph(HOME_TERMS);
 for(const view of [INITIAL_VIEW,{yaw:1.1,pitch:.5,zoom:.7},{yaw:-.8,pitch:-.4,zoom:1.4}]) {
  const points=projectGraph(graph,view);
  assert.equal(Object.keys(points).length,40);
  for(const node of graph.nodes) assert.deepEqual(points[node.id],projectNode(node,view));
  assert.ok(new Set(Object.values(points).map(p=>p.x.toFixed(2))).size>30);
  assert.ok(new Set(Object.values(points).map(p=>p.y.toFixed(2))).size>30);
 }
});
test('initial volume has front and back clusters and tilted camera; rotation changes parallax and scale',()=>{
 const graph=buildTermGraph(HOME_TERMS),before=projectGraph(graph,INITIAL_VIEW);
 assert.ok(INITIAL_VIEW.yaw!==0&&INITIAL_VIEW.pitch!==0);
 const categories=graph.nodes.filter(n=>!n.term);
 assert.ok(Math.max(...categories.map(n=>n.z))-Math.min(...categories.map(n=>n.z))>250);
 assert.ok(Math.max(...graph.nodes.map(n=>n.z))-Math.min(...graph.nodes.map(n=>n.z))>400);
 const after=projectGraph(graph,{...INITIAL_VIEW,yaw:INITIAL_VIEW.yaw+.7});
 assert.ok(graph.nodes.some(n=>Math.abs(after[n.id].depth-before[n.id].depth)>100));
 assert.ok(graph.nodes.some(n=>Math.abs(after[n.id].scale-before[n.id].scale)>.1));
 for(const point of Object.values(before)) assert.ok(point.x>0&&point.x<1000&&point.y>0&&point.y<700);
});

test('active catalog exposes only validated dependency ids and direct-search policy',()=>{
 assert.equal(ACTIVE_TERMS.length,82);
 const ids=new Set(ACTIVE_TERMS.map(term=>term.term_id));
 for(const term of ACTIVE_TERMS) for(const id of [...term.requires_all_of,...term.requires_any_of]) assert.ok(ids.has(id));
 assert.equal(ACTIVE_TERMS.find(term=>term.term_id==='pose_action').search_disabled,true);
 assert.equal(ACTIVE_TERMS.find(term=>term.term_id==='pose_sitting_on_edge').search_disabled,false);
});

test('expansion uses real catalog dependencies, preserves AND and OR parents, and deduplicates nodes',()=>{
 const graph=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,['pose_sitting','pose_sitting']);
 const ids=graph.nodes.map(node=>node.id);
 assert.equal(ids.length,new Set(ids).size);
 assert.ok(ids.includes('pose_sitting_on_edge'));
 assert.ok(ids.includes('pose_support_chair'));
 assert.deepEqual(
  graph.edges.filter(edge=>edge.target==='pose_sitting_on_edge').map(edge=>[edge.source,edge.relation]).sort(),
  [['pose_sitting','all'],['pose_support_chair','all']],
 );
 assert.deepEqual(
  graph.edges.filter(edge=>edge.target==='pose_action_two_hand_aiming').map(edge=>[edge.source,edge.relation]).sort(),
  [['pose_sitting','any'],['pose_standing','any']],
 );
 assert.ok(graph.nodes.find(node=>node.id==='pose_sitting').expandable);
 assert.ok(graph.nodes.find(node=>node.id==='pose_sitting_on_edge').isDetail);
 const sitting=graph.nodes.find(node=>node.id==='pose_sitting');
 const direct=graph.edges.filter(edge=>edge.source==='pose_sitting'&&edge.relation).map(edge=>graph.nodes.find(node=>node.id===edge.target));
 assert.ok(direct.every(node=>Math.hypot(node.x-sitting.x,node.y-sitting.y,node.z-sitting.z)>100));
});

test('collapse changes visibility only and cyclic relationships remain finite',()=>{
 const selected=['child'];
 assert.deepEqual(toggleExpanded(['root'],'root'),[]);
 assert.deepEqual(selected,['child']);
 const base=[{role:'pose',term_id:'root',label_ko:'root',requires_all_of:[],requires_any_of:[]}];
 const all=[...base,
  {role:'pose',term_id:'child',label_ko:'child',requires_all_of:['root','loop'],requires_any_of:[]},
  {role:'pose',term_id:'loop',label_ko:'loop',requires_all_of:['child'],requires_any_of:[]}];
 const graph=buildExpandedTermGraph(base,all,['root','child','loop']);
 assert.equal(graph.nodes.filter(node=>node.term).length,3);
 assert.equal(new Set(graph.edges.map(edge=>`${edge.source}:${edge.target}:${edge.relation}`)).size,graph.edges.length);
});

test('screen projection separates visible multi-branch labels and stays stable without a view change',()=>{
 const width=1440,height=900;
 const graph=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,['pose_sitting','pose_standing','pose_contrapposto']);
 const raw=projectGraph(graph,INITIAL_VIEW);
 const points=resolveGraphProjection(graph,INITIAL_VIEW,{width,height,topInset:74,bottomInset:150,rawPoints:raw});
 const visible=graph.nodes.filter(node=>node.term&&raw[node.id].depth>=-40).map(node=>({
  id:node.id,x:points[node.id].x,y:points[node.id].y,
  halfWidth:Math.min(190,44+[...node.label].length*11)*(node.expandable?1:1)*Math.max(.72,raw[node.id].scale)/2*1000/width
    +(node.expandable?20*Math.max(.72,raw[node.id].scale)*1000/width:0),
  halfHeight:Math.max(42,node.expandable?72:0)*Math.max(.72,raw[node.id].scale)/2*700/height,
 }));
 for(let first=0;first<visible.length;first++) for(let second=first+1;second<visible.length;second++) {
  const a=visible[first],b=visible[second];
  assert.ok(Math.abs(a.x-b.x)>=a.halfWidth+b.halfWidth||Math.abs(a.y-b.y)>=a.halfHeight+b.halfHeight,
   `${a.id} overlaps ${b.id}`);
 }
 const repeated=resolveGraphProjection(graph,INITIAL_VIEW,{width,height,topInset:74,bottomInset:150,rawPoints:raw,
  previousLayout:{points,raw}});
 assert.ok(Math.max(...graph.nodes.map(node=>Math.hypot(repeated[node.id].x-points[node.id].x,
  repeated[node.id].y-points[node.id].y)))<1);
});
