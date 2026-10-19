import test from 'node:test';
import assert from 'node:assert/strict';
import { HOME_TERMS } from '../lib/home-catalog.mjs';
import { buildTermGraph, projectNode, projectGraph, INITIAL_VIEW, toggleTerm, appendTerms } from '../lib/term-graph.mjs';

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
