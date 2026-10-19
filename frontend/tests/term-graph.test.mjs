import test from 'node:test';
import assert from 'node:assert/strict';
import { HOME_TERMS } from '../lib/home-catalog.mjs';
import { buildTermGraph, projectNode, separateGraphLabels, INITIAL_VIEW, toggleTerm, appendTerms } from '../lib/term-graph.mjs';

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

test('dense reviewed nodes remain separate on desktop and compact mobile projections',()=>{
 const graph=buildTermGraph(HOME_TERMS);
 for(const [width,height,compact] of [[990,600,false],[350,360,true]]) {
  const points=Object.values(separateGraphLabels(graph,INITIAL_VIEW,width,height,compact));
  assert.equal(points.length,40);
  for(let i=0;i<points.length;i++)for(let j=0;j<i;j++) {
   const a=points[i],b=points[j];
   assert.ok(Math.abs(a.x-b.x)*width/1000>=(a.w+b.w)/2-1 || Math.abs(a.y-b.y)*height/700>=(a.h+b.h)/2-1);
  }
 }
});
