import test from 'node:test';
import assert from 'node:assert/strict';
import { HOME_TERMS, catalogTerm } from '../lib/home-catalog.mjs';
import { createMindMapSlots } from '../lib/term-mind-map.mjs';
import { buildTermGraph, projectNode, INITIAL_VIEW } from '../lib/term-graph.mjs';
import { createDemoSessionStore, DEMO_SESSION_KEY } from '../lib/portfolio-demo-sessions.mjs';
import { DEMO_SCENARIOS } from '../lib/portfolio-demo-fixtures.mjs';

test('canonical composition contains every old view/layout card independently',()=>{
  const terms=HOME_TERMS.filter(t=>t.role==='composition');
  assert.equal(terms.length,13);
  assert.ok(terms.some(t=>t.term_id==='view_front'));
  assert.ok(terms.some(t=>t.term_id==='layout_composition'));
  assert.ok(terms.some(t=>t.term_id==='composition_rule_of_thirds'));
  assert.equal(catalogTerm('view_profile').role,'composition');
});
test('legacy result roles merge without dropping distinct cards',()=>{
 const slots=createMindMapSlots([{role:'view',term_id:'view_front',label_ko:'정면'},
 {role:'layout',term_id:'layout_composition',label_ko:'구도'},
 {role:'composition',term_id:'composition_rule_of_thirds',label_ko:'삼분할'}]);
 assert.deepEqual(slots[2].terms.map(t=>t.term_id),['view_front','layout_composition','composition_rule_of_thirds']);
 assert.equal(slots[2].roleLabel,'구도');
});
test('home graph grows actual reviewed nodes and keeps bounded projection',()=>{
 assert.deepEqual(Object.fromEntries(['body','pose','composition','perspective'].map(role=>[role,HOME_TERMS.filter(t=>t.role===role).length])),{body:6,pose:12,composition:13,perspective:5});
 for(const node of buildTermGraph(HOME_TERMS).nodes){
  const point=projectNode(node,INITIAL_VIEW);
  assert.ok(Number.isFinite(point.x)&&Number.isFinite(point.y));
  assert.ok(Math.abs(node.z)<=300);
 }
});
test('old demo prose restores from fixture IDs without discarding saved turns',()=>{
 const fixture=DEMO_SCENARIOS[0],sid='demo-legacy',tid='demo-turn';
 const saved={active:sid,sessions:[{session_id:sid,created_at:'2026-01-01T00:00:00Z',turns:[{id:tid,fixtureId:fixture.id,request:fixture.request,answer:fixture.job.result.answer_text.replaceAll('구도','시점')}]}]};
 const store=createDemoSessionStore({getItem:key=>key===DEMO_SESSION_KEY?JSON.stringify(saved):null,setItem:()=>{}});
 assert.equal(store.storageFailed,false);
 assert.equal(store.current().turns[0].id,tid);
});
