import test from 'node:test';
import assert from 'node:assert/strict';
import { ACTIVE_TERMS, HOME_TERMS } from '../lib/home-catalog.mjs';
import { buildTermGraph, buildExpandedTermGraph, projectNode, projectGraph, INITIAL_VIEW, toggleTerm, toggleExpanded, appendTerms } from '../lib/term-graph.mjs';
import { APPROVED_LAYOUT_SCALE } from '../lib/term-graph-approved-layout.mjs';

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
test('category hubs keep a little extra breathing room without changing the camera',()=>{
 const graph=buildTermGraph(HOME_TERMS),points=projectGraph(graph,INITIAL_VIEW);
 const categories=graph.nodes.filter(node=>!node.term).map(node=>points[node.id]);
 let minimum=Infinity;
 for(let first=0;first<categories.length;first++) for(let second=first+1;second<categories.length;second++)
  minimum=Math.min(minimum,Math.hypot(categories[first].x-categories[second].x,categories[first].y-categories[second].y));
 assert.ok(minimum>=180,`adjacent category hubs are only ${minimum}px apart`);
 assert.deepEqual(INITIAL_VIEW,{yaw:-.32,pitch:.18,zoom:.9});
});
test('projection rotates real depth and keeps extreme zoom finite', () => {
 const node={x:100,y:30,z:180};
 const front=projectNode(node,{yaw:0,pitch:0,zoom:1});
 const side=projectNode(node,{yaw:Math.PI/2,pitch:0,zoom:1});
 assert.notEqual(front.x,side.x);
 assert.notEqual(front.depth,side.depth);
 for(const zoom of [-100,100]) for(const value of Object.values(projectNode(node,{yaw:0,pitch:0,zoom}))) assert.ok(Number.isFinite(value));
});
test('camera origin is centered in the graph viewport',()=>{
 const point=projectNode({x:0,y:0,z:0},{yaw:0,pitch:0,zoom:1});
 assert.deepEqual({x:point.x,y:point.y},{x:500,y:420});
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

test('approved 3D layout uses the final inward body cluster and fixed 57-node universe',()=>{
 const parents=['pose_sitting','pose_standing','pose_contrapposto','pose_weight_shift','pose_s_curve','pose_kneeling'];
 const graph=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,parents),byId=new Map(graph.nodes.map(node=>[node.id,node]));
 assert.equal(graph.nodes.length,57);
 const bodyHub=byId.get('category:body');
 assert.ok(Math.abs(Math.hypot(bodyHub.x,bodyHub.y,bodyHub.z)-159.44840043098582)<1e-6,
  'body cluster must retain the approved additional 15% inward shift');
 const first=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,['pose_sitting']);
 const second=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,['pose_sitting','pose_contrapposto']);
 const secondById=new Map(second.nodes.map(node=>[node.id,node]));
 for(const node of first.nodes) assert.deepEqual({x:node.x,y:node.y,z:node.z},
  (({x,y,z})=>({x,y,z}))(secondById.get(node.id)),`${node.id} moved when another approved branch opened`);
});

test('perspective cluster aligns with the body hub height without changing its internal 3D offsets',()=>{
 const graph=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,
  ['pose_sitting','pose_standing','pose_contrapposto','pose_weight_shift','pose_s_curve','pose_kneeling']);
 const byId=new Map(graph.nodes.map(node=>[node.id,node])),points=projectGraph(graph,INITIAL_VIEW);
 const body=byId.get('category:body'),perspective=byId.get('category:perspective');
 assert.ok(Math.abs(points[body.id].y-points[perspective.id].y)<.01,
  `perspective hub is ${Math.abs(points[body.id].y-points[perspective.id].y).toFixed(2)}px away from body height`);
 const expectedRelativeOffsets=new Map([
  ['perspective_three_point',[15.06220973,69.775171819,98.14055625]],
  ['perspective_foreshortening',[53.906035835,24.647514165,88.833945045]],
  ['perspective_vanishing_point',[122.476531601,38.593195276,13.83525244]],
  ['perspective_one_point',[71.438236531,60.834736765,-51.615323909]],
  ['perspective_two_point',[22.604121029,139.704407408,34.14477631]],
 ]);
 for(const [id,[dx,dy,dz]] of expectedRelativeOffsets) {
  const node=byId.get(id);
  assert.ok(Math.abs(node.x-perspective.x-dx)<1e-6,`${id} x offset changed`);
  assert.ok(Math.abs(node.y-perspective.y-dy)<1e-6,`${id} y offset changed`);
  assert.ok(Math.abs(node.z-perspective.z-dz)<1e-6,`${id} z offset changed`);
 }
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
 assert.ok(!ids.includes('pose_support_chair'));
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
 assert.ok(direct.every(node=>Math.hypot(node.x-sitting.x,node.y-sitting.y,node.z-sitting.z)>80));
});

test('expanding one parent adds only its direct children, never supplemental parent nodes',()=>{
 const baseline=new Set(buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,[]).nodes.map(node=>node.id));
 const parents=HOME_TERMS.filter(parent=>ACTIVE_TERMS.some(child=>
  [...(child.requires_all_of||[]),...(child.requires_any_of||[])].includes(parent.term_id)));
 for(const parent of parents) {
  const direct=ACTIVE_TERMS.filter(child=>
   [...(child.requires_all_of||[]),...(child.requires_any_of||[])].includes(parent.term_id))
   .map(child=>child.term_id).filter(id=>!baseline.has(id)).sort();
  const added=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,[parent.term_id]).nodes
   .map(node=>node.id).filter(id=>!baseline.has(id)).sort();
  assert.deepEqual(added,direct,`${parent.term_id} expansion exposed nodes that are not its direct children`);
 }
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
 for(const [first,second] of [['pose_sitting','pose_standing'],['pose_standing','pose_sitting'],['pose_weight_shift','pose_s_curve']]) {
  const before=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,[first]);
  const after=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,[first,second]);
  const afterById=new Map(after.nodes.map(node=>[node.id,node]));
  for(const node of before.nodes) {
   const current=afterById.get(node.id);
   assert.ok(current,`${node.id} disappeared after ${second} expanded`);
   assert.deepEqual(
    {x:current.x,y:current.y,z:current.z},
    {x:node.x,y:node.y,z:node.z},
    `${node.id} moved when ${second} expanded`,
   );
  }
 }
});

test('each displayed child continues through its parent outward 3D cone',()=>{
 const graph=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,['pose_weight_shift']);
 assert.equal(graph.denseOverflow,false);
 const byId=new Map(graph.nodes.map(node=>[node.id,node]));
 const length=vector=>Math.hypot(vector.x,vector.y,vector.z);
 const unit=vector=>{const size=length(vector);return {x:vector.x/size,y:vector.y/size,z:vector.z/size};};
 const subtract=(a,b)=>({x:a.x-b.x,y:a.y-b.y,z:a.z-b.z});
 const angle=(a,b)=>Math.acos(Math.min(1,Math.max(-1,a.x*b.x+a.y*b.y+a.z*b.z)));
 for(const edge of graph.edges.filter(edge=>edge.relation&&byId.get(edge.target)?.isDetail)) {
  const parent=byId.get(edge.source),child=byId.get(edge.target),parentAxis=unit(parent);
  assert.ok(angle(unit(subtract(child,parent)),parentAxis)<Math.PI/3,
   `${child.id} does not continue outward from ${parent.id}`);
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

test('expanded branches keep extending outward from their displayed parents',()=>{
 const graph=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,['pose_sitting','pose_standing','pose_contrapposto']);
 const byId=new Map(graph.nodes.map(node=>[node.id,node]));
 const radius=node=>Math.hypot(node.x,node.y,node.z);
 const angle=(first,second)=>Math.acos(Math.min(1,Math.max(-1,
  (first.x*second.x+first.y*second.y+first.z*second.z)/(radius(first)*radius(second)))));
 for(const edge of graph.edges.filter(edge=>edge.relation&&byId.get(edge.target)?.isDetail)) {
  const parent=byId.get(edge.source),child=byId.get(edge.target);
  assert.ok(radius(child)>radius(parent)+1,`${child.id} returned inward past ${parent.id}`);
  const branch={x:child.x-parent.x,y:child.y-parent.y,z:child.z-parent.z};
  assert.ok(angle(parent,branch)<Math.PI/2,
   `${child.id} reversed across the outward axis of ${parent.id}`);
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

test('expanded branches keep a safe camera radius and perspective through every allowed orbit',()=>{
 const graph=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,
  ['pose_sitting','pose_standing','pose_contrapposto','pose_weight_shift','pose_s_curve','pose_kneeling']);
 const radii=graph.nodes.filter(node=>node.term).map(node=>Math.hypot(node.x,node.y,node.z));
 assert.ok(Math.max(...radii)<=650,`expanded world radius ${Math.max(...radii)} approaches the camera`);
 let closestGap=Infinity,maxPerspective=0;
 for(let yaw=-Math.PI;yaw<Math.PI;yaw+=Math.PI/18) for(let pitch=-1.2;pitch<=1.2;pitch+=.2) {
  const projected=projectGraph(graph,{yaw,pitch,zoom:1});
  for(const point of Object.values(projected)) {
   closestGap=Math.min(closestGap,1100-point.depth);
   maxPerspective=Math.max(maxPerspective,1100/(1100-point.depth));
  }
 }
 assert.ok(closestGap>=450,`camera clearance fell to ${closestGap}`);
 assert.ok(maxPerspective<=2.45,`perspective magnification reached ${maxPerspective}`);
});

test('approved 3D anchors avoid actual sphere collisions and stay finite through projection',()=>{
 const graph=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,['pose_weight_shift']);
 assert.equal(graph.denseOverflow,false);
 const points=projectGraph(graph,INITIAL_VIEW),radius=node=>(!node.term?31:node.isDetail?29:node.expandable?39:34)*APPROVED_LAYOUT_SCALE;
 for(let first=0;first<graph.nodes.length;first++) for(let second=first+1;second<graph.nodes.length;second++) {
  const a=graph.nodes[first],b=graph.nodes[second];
  assert.ok(Math.hypot(a.x-b.x,a.y-b.y,a.z-b.z)>=radius(a)+radius(b),`${a.id} collides with ${b.id} in 3D`);
 }
 assert.ok(Object.values(points).every(point=>Object.values(point).every(Number.isFinite)));
});

test('straight expanded relationship edges do not penetrate unrelated 3D node spheres',()=>{
 const graph=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,
  ['pose_weight_shift']);
 assert.equal(graph.denseOverflow,false,'representative expanded branches should remain in the 3D graph');
 const byId=new Map(graph.nodes.map(node=>[node.id,node]));
 const radius=node=>(!node.term?31:node.isDetail?29:node.expandable?39:34)*APPROVED_LAYOUT_SCALE;
 const distanceToSegment=(start,end,point)=>{
  const dx=end.x-start.x,dy=end.y-start.y,dz=end.z-start.z,lengthSquared=dx*dx+dy*dy+dz*dz;
  const t=lengthSquared?Math.max(0,Math.min(1,((point.x-start.x)*dx+(point.y-start.y)*dy+(point.z-start.z)*dz)/lengthSquared)):0;
  return {distance:Math.hypot(point.x-(start.x+t*dx),point.y-(start.y+t*dy),point.z-(start.z+t*dz)),t};
 };
 const crossings=[];
 for(const edge of graph.edges.filter(edge=>edge.relation)) {
  assert.equal(edge.route,undefined,`${edge.source}->${edge.target} must remain a straight edge`);
  const path=[byId.get(edge.source),byId.get(edge.target)];
  for(const node of graph.nodes.filter(node=>node.id!==edge.source&&node.id!==edge.target)) {
    const hit=distanceToSegment(path[0],path[1],node);
    if(hit.t>.001&&hit.t<.999&&hit.distance<radius(node))
     crossings.push(`${edge.source}->${edge.target} penetrates ${node.id} by ${(radius(node)-hit.distance).toFixed(2)} world units`);
  }
 }
 assert.deepEqual(crossings,[],'relationship edges must not penetrate unrelated 3D node spheres');
});

test('a sixteen-child fan keeps every term and requests the readable list fallback',()=>{
 const root={role:'pose',term_id:'dense_root',label_ko:'dense root',requires_all_of:[],requires_any_of:[]};
 const children=Array.from({length:16},(_,index)=>({role:'pose',term_id:`dense_child_${String(index).padStart(2,'0')}`,
  label_ko:`dense child ${index}`,requires_all_of:['dense_root'],requires_any_of:[]}));
 const graph=buildExpandedTermGraph([root],[root,...children],['dense_root']);
 assert.equal(graph.denseOverflow,true);
 assert.ok(children.every(child=>graph.nodes.some(node=>node.id===child.term_id)));
 assert.deepEqual(buildExpandedTermGraph([root],[root,...children],['dense_root']).nodes,graph.nodes);
});

test('the twelve-child sitting fan remains in the 3D graph with straight connectors',()=>{
 const graph=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,['pose_sitting']);
 const expected=ACTIVE_TERMS.filter(term=>[...(term.requires_all_of||[]),...(term.requires_any_of||[])].includes('pose_sitting'))
  .map(term=>term.term_id).sort();
 assert.equal(graph.denseOverflow,false);
 assert.ok(graph.nodes.filter(node=>node.isDetail).length>=12);
 assert.deepEqual(graph.nodes.filter(node=>node.isDetail).map(node=>node.id).sort(),expected);
 assert.ok(graph.edges.every(edge=>edge.route===undefined));
});

test('a five-child branch remains in the 3D graph without bent connectors',()=>{
 const graph=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,['pose_contrapposto']);
 const expected=ACTIVE_TERMS.filter(term=>[...(term.requires_all_of||[]),...(term.requires_any_of||[])].includes('pose_contrapposto'))
  .map(term=>term.term_id).sort();
 assert.equal(graph.denseOverflow,false);
 assert.deepEqual(graph.nodes.filter(node=>node.isDetail).map(node=>node.id).sort(),expected);
 assert.ok(graph.edges.every(edge=>edge.route===undefined));
});

test('every expansion subset keeps the fixed catalog layout collision-free',()=>{
 const parents=['pose_sitting','pose_standing','pose_contrapposto','pose_weight_shift','pose_s_curve','pose_kneeling'];
 const universe=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,parents);
 const stable=new Map(universe.nodes.map(node=>[node.id,{x:node.x,y:node.y,z:node.z}]));
 const radius=node=>(!node.term?31:node.isDetail?29:node.expandable?39:34)*APPROVED_LAYOUT_SCALE;
 const segmentClearance=(start,end,point)=>{
  const dx=end.x-start.x,dy=end.y-start.y,dz=end.z-start.z,squared=dx*dx+dy*dy+dz*dz,
   amount=squared?Math.max(0,Math.min(1,((point.x-start.x)*dx+(point.y-start.y)*dy+(point.z-start.z)*dz)/squared)):0;
  return {amount,clearance:Math.hypot(point.x-(start.x+dx*amount),point.y-(start.y+dy*amount),point.z-(start.z+dz*amount))-radius(point)};
 };
 for(let mask=0;mask<2**parents.length;mask++) {
  const expanded=parents.filter((_,index)=>mask&(1<<index));
  const graph=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,expanded);
  assert.equal(graph.denseOverflow,false,`unsafe expansion subset: ${expanded.join(', ')||'(none)'}`);
  assert.ok(graph.edges.every(edge=>edge.route===undefined),'expanded relations must remain straight');
  const expected=new Set(ACTIVE_TERMS.filter(term=>[...(term.requires_all_of||[]),...(term.requires_any_of||[])]
    .some(parent=>expanded.includes(parent))).map(term=>term.term_id));
  assert.deepEqual(new Set(graph.nodes.filter(node=>node.isDetail).map(node=>node.id)),expected,
    `wrong direct children for: ${expanded.join(', ')||'(none)'}`);
  for(const node of graph.nodes) assert.deepEqual({x:node.x,y:node.y,z:node.z},stable.get(node.id),
    `${node.id} moved in subset: ${expanded.join(', ')||'(none)'}`);
  const byId=new Map(graph.nodes.map(node=>[node.id,node]));
  for(const edge of graph.edges) {
   const start=byId.get(edge.source),end=byId.get(edge.target);
   for(const obstacle of graph.nodes) if(obstacle.id!==edge.source&&obstacle.id!==edge.target) {
    const hit=segmentClearance(start,end,obstacle);
    assert.ok(hit.amount<=.001||hit.amount>=.999||hit.clearance>=0,
     `${edge.source} -> ${edge.target} penetrated ${obstacle.id} by ${hit.clearance.toFixed(2)} world units`);
   }
  }
 }
});

test('an unsafe synthetic dense fan requests the readable list representation',()=>{
 const root={role:'pose',term_id:'overflow_root',label_ko:'overflow root',requires_all_of:[],requires_any_of:[]};
 const children=Array.from({length:20},(_,index)=>({role:'pose',term_id:`overflow_child_${String(index).padStart(2,'0')}`,
  label_ko:`overflow child ${index}`,requires_all_of:['overflow_root'],requires_any_of:[]}));
 const graph=buildExpandedTermGraph([root],[root,...children],['overflow_root']);
 assert.equal(graph.denseOverflow,true);
 const ids=new Set(graph.nodes.map(node=>node.id));
 assert.ok(['overflow_root',...children.map(child=>child.term_id)].every(id=>ids.has(id)));
 assert.equal(graph.relationships.filter(edge=>edge.source==='overflow_root').length,20);
});

test('a deep dense fan keeps every term when straight placement requires the list',()=>{
 const root={role:'pose',term_id:'two_level_root',label_ko:'two level root',requires_all_of:[],requires_any_of:[]};
 const middle={role:'pose',term_id:'two_level_middle',label_ko:'two level middle',requires_all_of:['two_level_root'],requires_any_of:[]};
 const children=Array.from({length:4},(_,index)=>({role:'pose',term_id:`two_level_child_${index}`,
  label_ko:`two level child ${index}`,requires_all_of:['two_level_middle'],requires_any_of:[]}));
 const graph=buildExpandedTermGraph([root],[root,middle,...children],['two_level_root','two_level_middle']);
 assert.equal(graph.denseOverflow,true);
 assert.ok(children.every(child=>graph.nodes.some(node=>node.id===child.term_id)));
});

test('a dense fan whose deep parent cannot be placed uses the readable list representation',()=>{
 const chain=Array.from({length:4},(_,index)=>({role:'pose',term_id:`deep_${index}`,label_ko:`deep ${index}`,
  requires_all_of:index?[`deep_${index-1}`]:[],requires_any_of:[]}));
 const children=Array.from({length:4},(_,index)=>({role:'pose',term_id:`deep_child_${index}`,label_ko:`deep child ${index}`,
  requires_all_of:['deep_3'],requires_any_of:[]}));
 const graph=buildExpandedTermGraph([chain[0]],[...chain,...children],chain.map(term=>term.term_id));
 assert.equal(graph.denseOverflow,true);
 assert.ok(children.every(child=>graph.nodes.some(node=>node.id===child.term_id)));
});
