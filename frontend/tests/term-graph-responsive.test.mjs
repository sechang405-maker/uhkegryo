import test from 'node:test';
import assert from 'node:assert/strict';
import { assessGraphViewport } from '../lib/term-graph-responsive.mjs';

const termNode=(id,{detail=false,expandable=true}={})=>({
 id,term:{term_id:id},isDetail:detail,expandable,
});

test('fixed-size graph circles remain safe when the panel preserves their spacing',()=>{
 const nodes=[termNode('a'),termNode('b'),termNode('c')];
 const points={a:{x:100,y:300},b:{x:210,y:300},c:{x:320,y:300}};
 const result=assessGraphViewport(nodes,points,{width:1000,height:840});
 assert.equal(result.unsafe,false);
 assert.equal(result.severeOverlapCount,0);
 assert.ok(result.minimumRatio>1);
});

test('narrow panel compression requests the readable list when several fixed circles collide',()=>{
 const nodes=[termNode('a'),termNode('b'),termNode('c')];
 const points={a:{x:100,y:300},b:{x:210,y:300},c:{x:320,y:300}};
 const result=assessGraphViewport(nodes,points,{width:600,height:840});
 assert.equal(result.unsafe,true);
 assert.equal(result.reason,'overlap');
 assert.equal(result.severeOverlapCount,2);
 assert.ok(result.minimumRatio<.72);
});

test('one shallow overlap does not force a view change but a near-stacked pair does',()=>{
 const nodes=[termNode('a'),termNode('b')];
 assert.equal(assessGraphViewport(nodes,{a:{x:100,y:300},b:{x:164,y:300}},{width:1000,height:840}).unsafe,false);
 const critical=assessGraphViewport(nodes,{a:{x:100,y:300},b:{x:150,y:300}},{width:1000,height:840});
 assert.equal(critical.unsafe,true);
 assert.equal(critical.reason,'critical-overlap');
});

test('a circle clipped by the actual panel requests the readable list',()=>{
 const nodes=[termNode('detail',{detail:true,expandable:false})];
 const result=assessGraphViewport(nodes,{detail:{x:20,y:300}},{width:800,height:840});
 assert.equal(result.unsafe,true);
 assert.equal(result.reason,'clipped');
 assert.equal(result.clippedCount,1);
});
