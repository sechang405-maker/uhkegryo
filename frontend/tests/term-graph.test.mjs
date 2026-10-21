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
 const categoryDepths=categories.map(node=>before[node.id].depth);
 assert.ok(Math.max(...categoryDepths)-Math.min(...categoryDepths)>200,'category sectors retain meaningful camera depth');
 assert.ok(Math.max(...graph.nodes.map(n=>n.z))-Math.min(...graph.nodes.map(n=>n.z))>400,'term fan retains substantial world z depth');
 const allDepths=Object.values(before).map(point=>point.depth);
 assert.ok(Math.max(...allDepths)-Math.min(...allDepths)>500,'initial camera retains strong projected depth separation');
 const after=projectGraph(graph,{...INITIAL_VIEW,yaw:INITIAL_VIEW.yaw+.7});
 assert.ok(graph.nodes.some(n=>Math.hypot(after[n.id].x-before[n.id].x,after[n.id].y-before[n.id].y)>100));
 assert.ok(graph.nodes.some(node=>Math.abs(after[node.id].depth-before[node.id].depth)>1));
 assert.ok(graph.nodes.some(node=>Math.abs(after[node.id].scale-before[node.id].scale)>.001));
 for(const point of Object.values(before)) assert.ok(point.x>0&&point.x<1000&&point.y>0&&point.y<840);
});

test('active catalog exposes only validated dependency ids and direct-search policy',()=>{
 assert.equal(ACTIVE_TERMS.length,82);
 const ids=new Set(ACTIVE_TERMS.map(term=>term.term_id));
 for(const term of ACTIVE_TERMS) for(const id of [...term.requires_all_of,...term.requires_any_of]) assert.ok(ids.has(id));
 assert.equal(ACTIVE_TERMS.find(term=>term.term_id==='pose_action').search_disabled,true);
 assert.equal(ACTIVE_TERMS.find(term=>term.term_id==='pose_sitting_on_edge').search_disabled,false);
});

test('expansion preserves semantic AND/OR parents but renders one representative parent per child',()=>{
 const graph=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,['pose_sitting','pose_sitting']);
 const ids=graph.nodes.map(node=>node.id);
 assert.equal(ids.length,new Set(ids).size);
 assert.ok(ids.includes('pose_sitting_on_edge'));
 assert.ok(ids.includes('pose_support_chair'));
 assert.deepEqual(
  graph.edges.filter(edge=>edge.target==='pose_sitting_on_edge').map(edge=>[edge.source,edge.relation]).sort(),
  [['pose_sitting','all']],
 );
 assert.deepEqual(
  graph.edges.filter(edge=>edge.target==='pose_action_two_hand_aiming').map(edge=>[edge.source,edge.relation]).sort(),
  [['pose_sitting','any']],
 );
 assert.deepEqual(graph.relationships.filter(edge=>edge.target==='pose_sitting_on_edge').map(edge=>[edge.source,edge.relation]).sort(),
  [['pose_sitting','all'],['pose_support_chair','all']]);
 assert.deepEqual(graph.relationships.filter(edge=>edge.target==='pose_action_two_hand_aiming').map(edge=>[edge.source,edge.relation]).sort(),
  [['pose_sitting','any'],['pose_standing','any']]);
 const incoming=new Map();
 for(const edge of graph.edges) incoming.set(edge.target,(incoming.get(edge.target)||0)+1);
 assert.ok(graph.nodes.filter(node=>node.term).every(node=>(incoming.get(node.id)||0)<=1));
 assert.ok(graph.nodes.find(node=>node.id==='pose_sitting').expandable);
 assert.ok(graph.nodes.find(node=>node.id==='pose_sitting_on_edge').isDetail);
 const sitting=graph.nodes.find(node=>node.id==='pose_sitting');
 const direct=graph.edges.filter(edge=>edge.source==='pose_sitting'&&edge.relation).map(edge=>graph.nodes.find(node=>node.id===edge.target));
 assert.ok(direct.every(node=>Math.hypot(node.x-sitting.x,node.y-sitting.y,node.z-sitting.z)>100));
});

test('the first expanded shared parent keeps visual ownership until it collapses, independent of later expansion',()=>{
 const parentOf=(graph,target)=>graph.edges.find(edge=>edge.target===target)?.source;
 const sittingOnly=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,['pose_sitting']);
 const sittingFirst=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,['pose_sitting','pose_standing']);
 assert.equal(parentOf(sittingOnly,'pose_action_two_hand_aiming'),'pose_sitting');
 assert.equal(parentOf(sittingFirst,'pose_action_two_hand_aiming'),'pose_sitting');
 const before=sittingOnly.nodes.find(node=>node.id==='pose_action_two_hand_aiming');
 const after=sittingFirst.nodes.find(node=>node.id==='pose_action_two_hand_aiming');
 assert.deepEqual({x:after.x,y:after.y,z:after.z},{x:before.x,y:before.y,z:before.z});
 const standingOnly=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,['pose_standing']);
 const standingThenSitting=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,['pose_standing','pose_sitting']);
 assert.equal(parentOf(standingOnly,'pose_action_two_hand_aiming'),'pose_standing');
 assert.equal(parentOf(standingThenSitting,'pose_action_two_hand_aiming'),'pose_standing');
 assert.equal(standingThenSitting.nodes.filter(node=>node.id==='pose_action_two_hand_aiming').length,1);
});

test('expanding an unrelated parent leaves every existing world coordinate unchanged',()=>{
 const before=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,['pose_sitting']);
 const after=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,['pose_sitting','pose_standing']);
 const afterById=new Map(after.nodes.map(node=>[node.id,node]));
 for(const node of before.nodes) {
  const current=afterById.get(node.id);
  assert.ok(current,`${node.id} disappeared after an unrelated expansion`);
  assert.deepEqual(
   {x:current.x,y:current.y,z:current.z},
   {x:node.x,y:node.y,z:node.z},
   `${node.id} moved when another branch expanded`,
  );
 }
});

test('each displayed child continues through its parent outward axis without entering a neighboring parent territory',()=>{
 const graph=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,['pose_sitting','pose_standing','pose_contrapposto']);
 const byId=new Map(graph.nodes.map(node=>[node.id,node]));
 const length=vector=>Math.hypot(vector.x,vector.y,vector.z);
 const unit=vector=>{const size=length(vector);return {x:vector.x/size,y:vector.y/size,z:vector.z/size};};
 const subtract=(a,b)=>({x:a.x-b.x,y:a.y-b.y,z:a.z-b.z});
 const angle=(a,b)=>Math.acos(Math.min(1,Math.max(-1,a.x*b.x+a.y*b.y+a.z*b.z)));
 const points=projectGraph(graph,INITIAL_VIEW),screenAngle=id=>Math.atan2(points[id].y-420,points[id].x-500),
  angularDistance=(a,b)=>Math.abs(Math.atan2(Math.sin(a-b),Math.cos(a-b)));
 const displayedParents=[...new Set(graph.edges.filter(edge=>edge.relation).map(edge=>edge.source))].map(id=>byId.get(id));
 for(const edge of graph.edges.filter(edge=>edge.relation)) {
  const parent=byId.get(edge.source),child=byId.get(edge.target),parentAxis=unit(parent);
  assert.ok(angle(unit(subtract(child,parent)),parentAxis)<Math.PI/3,
   `${child.id} does not continue outward from ${parent.id}`);
  const nearest=Math.min(...displayedParents.filter(candidate=>candidate.role===parent.role&&candidate.id!==parent.id&&
    ((parent.childCount||0)<3||(candidate.childCount||0)>=3))
   .map(candidate=>angularDistance(screenAngle(parent.id),screenAngle(candidate.id))),Math.PI/2);
  assert.ok(angularDistance(screenAngle(child.id),screenAngle(parent.id))<=nearest/2+.04,
   `${child.id} entered a neighboring parent branch territory`);
 }
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

test('expanded branches stay in their category cone and every real child is farther from the graph center than its parents',()=>{
 const graph=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,['pose_sitting','pose_standing','pose_contrapposto']);
 const byId=new Map(graph.nodes.map(node=>[node.id,node]));
 const radius=node=>Math.hypot(node.x,node.y,node.z);
 const angle=(a,b)=>Math.acos(Math.min(1,Math.max(-1,(a.x*b.x+a.y*b.y+a.z*b.z)/(radius(a)*radius(b)))));
 for(const node of graph.nodes.filter(node=>node.term)) {
  const category=byId.get(`category:${node.role}`);
  assert.ok(angle(node,category)<Math.PI/3,`${node.id} escaped the ${node.role} category cone`);
 }
 for(const edge of graph.edges.filter(edge=>edge.relation)) {
  const parent=byId.get(edge.source),child=byId.get(edge.target);
  assert.ok(radius(child)>radius(parent)+1,`${child.id} returned inward past ${parent.id}`);
 }
});

test('simultaneous category fans and a two-level branch keep extending outward, including a multi-parent child',()=>{
 const base=[
  {role:'body',term_id:'body_root',label_ko:'body root',requires_all_of:[],requires_any_of:[]},
  {role:'pose',term_id:'pose_root',label_ko:'pose root',requires_all_of:[],requires_any_of:[]},
  {role:'pose',term_id:'pose_support',label_ko:'pose support',requires_all_of:[],requires_any_of:[]},
 ];
 const catalog=[...base,
  {role:'body',term_id:'body_child',label_ko:'body child',requires_all_of:['body_root'],requires_any_of:[]},
  {role:'pose',term_id:'pose_child',label_ko:'pose child',requires_all_of:['pose_root','pose_support'],requires_any_of:[]},
  {role:'pose',term_id:'pose_grandchild',label_ko:'pose grandchild',requires_all_of:['pose_child'],requires_any_of:[]},
 ];
 const graph=buildExpandedTermGraph(base,catalog,['body_root','pose_root','pose_child']);
 const byId=new Map(graph.nodes.map(node=>[node.id,node])),radius=id=>{const node=byId.get(id);return Math.hypot(node.x,node.y,node.z)};
 assert.ok(radius('body_child')>radius('body_root'));
 assert.ok(radius('pose_child')>Math.max(radius('pose_root'),radius('pose_support')));
 assert.ok(radius('pose_grandchild')>radius('pose_child'));
 const poseCategory=byId.get('category:pose'),poseGrandchild=byId.get('pose_grandchild');
 const cosine=(poseCategory.x*poseGrandchild.x+poseCategory.y*poseGrandchild.y+poseCategory.z*poseGrandchild.z)/(radius('category:pose')*radius('pose_grandchild'));
 assert.ok(Math.acos(Math.min(1,Math.max(-1,cosine)))<Math.PI/3,'grandchild crossed into another category sector');
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

test('circular graph anchors avoid stacked centers and stay near the initial camera frame',()=>{
 const graph=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,['pose_sitting','pose_standing','pose_contrapposto']);
 const points=projectGraph(graph,INITIAL_VIEW);
 const visible=graph.nodes.filter(node=>node.term).map(node=>{
  const scale=node.isDetail?1:Math.max(.9,Math.min(1,points[node.id].scale)),radius=(node.isDetail?26:node.expandable?34:28)*scale;
  return {id:node.id,x:points[node.id].x,y:points[node.id].y,radius};
 });
 const severe=[];
 for(let first=0;first<visible.length;first++) for(let second=first+1;second<visible.length;second++) {
  const a=visible[first],b=visible[second];
  const distance=Math.hypot(a.x-b.x,a.y-b.y),combined=a.radius+b.radius;
  if(distance<combined*.4) severe.push([a.id,b.id,distance/combined]);
 }
 assert.deepEqual(severe,[],'no circular node centers may stack inside one another');
 assert.ok(visible.every(node=>node.x>-30&&node.x<1050&&node.y>-30&&node.y<870),'initial camera keeps every anchor near the frame');
});
