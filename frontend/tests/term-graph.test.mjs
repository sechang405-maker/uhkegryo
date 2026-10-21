import test from 'node:test';
import assert from 'node:assert/strict';
import { ACTIVE_TERMS, HOME_TERMS } from '../lib/home-catalog.mjs';
import { buildTermGraph, buildExpandedTermGraph, projectNode, projectGraph, INITIAL_VIEW, toggleTerm, toggleExpanded, appendTerms } from '../lib/term-graph.mjs';

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

test('initial rendered anchors use the world projection without grid or screen repacking',()=>{
 const graph=buildTermGraph(HOME_TERMS);
 const points=projectGraph(graph,INITIAL_VIEW);
 assert.equal(Object.keys(points).length,40);
 for(const node of graph.nodes) assert.deepEqual(points[node.id],projectNode(node,INITIAL_VIEW));
 assert.ok(new Set(Object.values(points).map(p=>p.x.toFixed(2))).size>30);
 assert.ok(new Set(Object.values(points).map(p=>p.y.toFixed(2))).size>30);
});
test('world data stays fixed while yaw changes the projected depth',()=>{
 const graph=buildTermGraph(HOME_TERMS),before=projectGraph(graph,INITIAL_VIEW);
 assert.ok(INITIAL_VIEW.yaw!==0&&INITIAL_VIEW.pitch!==0);
 const categories=graph.nodes.filter(n=>!n.term);
 assert.ok(Math.max(...categories.map(n=>n.z))-Math.min(...categories.map(n=>n.z))>250);
 assert.ok(Math.max(...graph.nodes.map(n=>n.z))-Math.min(...graph.nodes.map(n=>n.z))>400);
 const after=projectGraph(graph,{...INITIAL_VIEW,yaw:INITIAL_VIEW.yaw+.7});
 assert.ok(graph.nodes.some(n=>Math.hypot(after[n.id].x-before[n.id].x,after[n.id].y-before[n.id].y)>100));
 assert.ok(graph.nodes.some(node=>Math.abs(after[node.id].depth-before[node.id].depth)>1));
 assert.ok(graph.nodes.some(node=>Math.abs(after[node.id].scale-before[node.id].scale)>.001));
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

test('expanded graph keeps one deterministic world layout through rotation and zoom',()=>{
 const graph=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,['pose_sitting','pose_standing','pose_contrapposto']);
 const world=graph.nodes.map(({id,x,y,z})=>({id,x,y,z}));
 for(let step=0;step<24;step++) projectGraph(graph,{yaw:-Math.PI+step*Math.PI/12,pitch:(step%7-3)*.12,zoom:.65+(step%8)*.12});
 assert.deepEqual(graph.nodes.map(({id,x,y,z})=>({id,x,y,z})),world);
 assert.deepEqual(buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,['pose_sitting','pose_standing','pose_contrapposto']).nodes,graph.nodes);
});

test('camera motion uses independent yaw and pitch in one 3D projection without mutating world anchors',()=>{
 const graph=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,['pose_sitting','pose_standing','pose_contrapposto']);
 const world=graph.nodes.map(({id,x,y,z})=>({id,x,y,z}));
 const yawView={...INITIAL_VIEW,yaw:INITIAL_VIEW.yaw+.63};
 const pitchView={...INITIAL_VIEW,pitch:INITIAL_VIEW.pitch-.31};
 const yaw=projectGraph(graph,yawView),pitch=projectGraph(graph,pitchView);
 for(const node of graph.nodes) {
  assert.deepEqual(yaw[node.id],projectNode(node,yawView));
  assert.deepEqual(pitch[node.id],projectNode(node,pitchView));
 }
 assert.ok(graph.nodes.some(node=>Math.abs(yaw[node.id].depth-pitch[node.id].depth)>1));
 assert.ok(graph.nodes.some(node=>Math.hypot(yaw[node.id].x-pitch[node.id].x,yaw[node.id].y-pitch[node.id].y)>10));
 assert.deepEqual(graph.nodes.map(({id,x,y,z})=>({id,x,y,z})),world);
});

test('structure-time world layout separates visible labels in the initial camera view',()=>{
 const width=1000,height=700;
 const graph=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,['pose_sitting','pose_standing','pose_contrapposto']);
 const points=projectGraph(graph,INITIAL_VIEW);
 const visible=graph.nodes.filter(node=>node.term&&points[node.id].depth>=-40).map(node=>{
  const scale=Math.max(.72,points[node.id].scale);
  return {id:node.id,x:points[node.id].x,y:points[node.id].y,
   halfWidth:(Math.min(190,44+[...node.label].length*11)+(node.expandable?40:0))*scale/2*1000/width,
   halfHeight:Math.max(42,node.expandable?72:0)*scale/2*700/height};
 });
 const overlaps=[];
 for(let first=0;first<visible.length;first++) for(let second=first+1;second<visible.length;second++) {
  const a=visible[first],b=visible[second];
  if(Math.abs(a.x-b.x)<a.halfWidth+b.halfWidth&&Math.abs(a.y-b.y)<a.halfHeight+b.halfHeight) overlaps.push([a.id,b.id]);
 }
 assert.deepEqual(overlaps,[]);
});
