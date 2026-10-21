import test from 'node:test';
import assert from 'node:assert/strict';
import { INITIAL_VIEW, projectNode } from '../lib/term-graph.mjs';
import {
  createGraphMotionState,
  reconcileGraphMotion,
  finishGraphMotion,
  pauseGraphMotion,
  interpolateGraphMotion,
  motionAmount,
} from '../lib/term-graph-motion.mjs';

const node=(id,x,y=0,z=0)=>({id,label:id,x,y,z,term:{term_id:id}});
const graph=(nodes,edges=[])=>({nodes,edges,relationships:[],denseOverflow:false});

test('new children enter from their toggled parent without moving another branch',()=>{
 const initial=graph([node('parent',0),node('other',80)]);
 const expanded=graph([node('parent',0),node('other',80),node('child',40)],
  [{source:'parent',target:'child',relation:'all'}]);
 const state=reconcileGraphMotion(createGraphMotionState(initial),expanded,['parent'],'parent',100,240,false);
 assert.deepEqual(state.expandedIds,['parent']);
 assert.equal(state.displayGraph.nodes.length,3);
 assert.equal(motionAmount(state.presence.child,100),0);
 const start=interpolateGraphMotion(state.displayGraph,state.presence,INITIAL_VIEW,100);
 const parentPoint=projectNode(initial.nodes[0],INITIAL_VIEW),otherPoint=projectNode(initial.nodes[1],INITIAL_VIEW);
 assert.equal(start.points.other.x,otherPoint.x);
 assert.equal(start.points.other.y,otherPoint.y);
 assert.equal(start.points.child.x,parentPoint.x);
 assert.equal(start.points.child.y,parentPoint.y);
 assert.equal(start.points.child.presence,0);
 const middle=interpolateGraphMotion(state.displayGraph,state.presence,INITIAL_VIEW,220);
 assert.notEqual(middle.points.child.x,parentPoint.x);
 assert.equal(middle.points.other.x,otherPoint.x);
 assert.equal(middle.points.other.y,otherPoint.y);
});

test('collapse keeps an inert snapshot until completion and then removes it',()=>{
 const expanded=graph([node('parent',0),node('child',40)],
  [{source:'parent',target:'child',relation:'all'}]);
 let state=createGraphMotionState(expanded,['parent']);
 const collapsed=graph([node('parent',0)]);
 state=reconcileGraphMotion(state,collapsed,[],'parent',500,240,false);
 assert.equal(state.displayGraph.nodes.some(item=>item.id==='child'),true);
 assert.equal(state.presence.child.target,0);
 assert.equal(state.displayGraph.edges.filter(edge=>edge.target==='child').length,1);
 state=finishGraphMotion(state,740);
 assert.equal(state.displayGraph.nodes.some(item=>item.id==='child'),false);
 assert.equal(state.displayGraph.edges.some(edge=>edge.target==='child'),false);
 assert.equal(state.presence.child,undefined);
});

test('rapid reversal continues from the current amount instead of restarting',()=>{
 const collapsed=graph([node('parent',0)]),expanded=graph([node('parent',0),node('child',40)],
  [{source:'parent',target:'child',relation:'all'}]);
 let state=reconcileGraphMotion(createGraphMotionState(collapsed),expanded,['parent'],'parent',0,240,false);
 const before=interpolateGraphMotion(state.displayGraph,state.presence,INITIAL_VIEW,90).points.child;
 state=reconcileGraphMotion(state,collapsed,[],'parent',90,240,false);
 const afterCollapse=interpolateGraphMotion(state.displayGraph,state.presence,INITIAL_VIEW,90).points.child;
 assert.ok(Math.hypot(afterCollapse.x-before.x,afterCollapse.y-before.y)<1e-9);
 const beforeExpand=interpolateGraphMotion(state.displayGraph,state.presence,INITIAL_VIEW,120).points.child;
 state=reconcileGraphMotion(state,expanded,['parent'],'parent',120,240,false);
 const afterExpand=interpolateGraphMotion(state.displayGraph,state.presence,INITIAL_VIEW,120).points.child;
 assert.ok(Math.hypot(afterExpand.x-beforeExpand.x,afterExpand.y-beforeExpand.y)<1e-9);
 assert.equal(state.displayGraph.nodes.filter(item=>item.id==='child').length,1);
});

test('reduced motion settles immediately with no retained callbacks',()=>{
 const expanded=graph([node('parent',0),node('child',40)],[{source:'parent',target:'child',relation:'all'}]);
 const collapsed=graph([node('parent',0)]);
 let state=createGraphMotionState(expanded,['parent']);
 state=reconcileGraphMotion(state,collapsed,[],'parent',0,240,true);
 assert.deepEqual(state.expandedIds,[]);
 assert.deepEqual(state.displayGraph.nodes.map(item=>item.id),['parent']);
 assert.deepEqual(state.presence,{});
});

test('pausing shifts the clock so hidden time does not advance motion',()=>{
 const expanded=graph([node('parent',0),node('child',40)],[{source:'parent',target:'child',relation:'all'}]);
 let state=reconcileGraphMotion(createGraphMotionState(graph([node('parent',0)])),expanded,['parent'],'parent',100,240,false);
 const before=motionAmount(state.presence.child,180);
 state=pauseGraphMotion(state,400);
 assert.ok(Math.abs(motionAmount(state.presence.child,580)-before)<1e-9);
});

test('a shared child that remains active never retains a second exit edge',()=>{
 const first=graph([node('a',0),node('b',10),node('shared',30)],[{source:'a',target:'shared',relation:'any'}]);
 const second=graph([node('a',0),node('b',10),node('shared',30)],[{source:'b',target:'shared',relation:'any'}]);
 const state=reconcileGraphMotion(createGraphMotionState(first,['a','b']),second,['b'],'a',10,240,false);
 assert.equal(state.displayGraph.nodes.filter(item=>item.id==='shared').length,1);
 assert.deepEqual(state.displayGraph.edges.filter(edge=>edge.target==='shared').map(edge=>edge.source),['b']);
});

test('an unrelated toggle neither retargets nor restarts another branch in flight',()=>{
 const base=graph([node('a',0),node('b',10)]);
 const both=graph([node('a',0),node('b',10),node('a-child',30),node('b-child',40)],
  [{source:'a',target:'a-child',relation:'all'},{source:'b',target:'b-child',relation:'all'}]);
 let state=reconcileGraphMotion(createGraphMotionState(base),
  graph([node('a',0),node('b',10),node('a-child',30)],[{source:'a',target:'a-child',relation:'all'}]),['a'],'a',0,180,false);
 const original=state.presence['a-child'];
 state=reconcileGraphMotion(state,both,['a','b'],'b',50,180,false);
 assert.deepEqual(state.presence['a-child'],original,'unrelated expansion restarted the existing transition');
 state=reconcileGraphMotion(state,
  graph([node('a',0),node('b',10),node('b-child',40)],[{source:'b',target:'b-child',relation:'all'}]),['b'],'a',70,180,false);
 const exiting=state.presence['a-child'];
 state=reconcileGraphMotion(state,base,[],'b',90,180,false);
 assert.equal(state.presence['a-child'].anchorId,'a','another collapse retargeted the exiting branch');
 assert.equal(state.presence['a-child'].startedAt,exiting.startedAt,'another collapse restarted the exiting branch');
});

test('a retained shared child glides between visual owners instead of snapping',()=>{
 const first=graph([node('a',0),node('b',10),node('shared',30)],[{source:'a',target:'shared',relation:'any'}]);
 const second=graph([node('a',0),node('b',10),node('shared',80)],[{source:'b',target:'shared',relation:'any'}]);
 const state=reconcileGraphMotion(createGraphMotionState(first,['a','b']),second,['b'],'a',100,180,false);
 const motion=state.presence.shared;
 assert.equal(motion.alphaFrom,1);
 assert.equal(motion.alphaTo,1);
 assert.ok(motion.originId);
 const origin=state.displayGraph.nodes.find(item=>item.id===motion.originId);
 assert.equal(origin.motionOrigin,true);
 assert.equal(origin.x,30);
 const start=interpolateGraphMotion(state.displayGraph,state.presence,INITIAL_VIEW,100).points.shared;
 const originPoint=projectNode(origin,INITIAL_VIEW);
 assert.equal(start.x,originPoint.x);
 assert.equal(start.y,originPoint.y);
 assert.equal(start.opacity,originPoint.opacity);
 const finished=finishGraphMotion(state,280);
 assert.equal(finished.displayGraph.nodes.some(item=>item.motionOrigin),false);
});

test('owner glide can be interrupted by final collapse without a jump or stale helper',()=>{
 const first=graph([node('a',0),node('b',10),node('shared',30)],[{source:'a',target:'shared',relation:'any'}]);
 const transferred=graph([node('a',0),node('b',10),node('shared',80)],[{source:'b',target:'shared',relation:'any'}]);
 const empty=graph([node('a',0),node('b',10)]);
 let state=reconcileGraphMotion(createGraphMotionState(first,['a','b']),transferred,['b'],'a',0,180,false);
 const before=interpolateGraphMotion(state.displayGraph,state.presence,INITIAL_VIEW,60).points.shared;
 state=reconcileGraphMotion(state,empty,[],'b',60,180,false);
 const after=interpolateGraphMotion(state.displayGraph,state.presence,INITIAL_VIEW,60).points.shared;
 assert.ok(Math.hypot(after.x-before.x,after.y-before.y)<1e-9,'interrupting exit jumped at the same timestamp');
 assert.equal(state.presence.shared.alphaFrom,1);
 assert.equal(state.presence.shared.alphaTo,0);
 state=finishGraphMotion(state,240);
 assert.equal(state.displayGraph.nodes.some(item=>item.id==='shared'||item.motionOrigin),false);
});

test('a second owner transfer restarts from the current glide position',()=>{
 const first=graph([node('a',0),node('b',10),node('shared',30)],[{source:'a',target:'shared',relation:'any'}]);
 const second=graph([node('a',0),node('b',10),node('shared',80)],[{source:'b',target:'shared',relation:'any'}]);
 const third=graph([node('a',0),node('b',10),node('shared',50)],[{source:'a',target:'shared',relation:'any'}]);
 let state=reconcileGraphMotion(createGraphMotionState(first,['a','b']),second,['b'],'a',0,180,false);
 const before=interpolateGraphMotion(state.displayGraph,state.presence,INITIAL_VIEW,60).points.shared;
 state=reconcileGraphMotion(state,third,['a'],'b',60,180,false);
 const after=interpolateGraphMotion(state.displayGraph,state.presence,INITIAL_VIEW,60).points.shared;
 assert.ok(Math.hypot(after.x-before.x,after.y-before.y)<1e-9,'second owner transfer jumped at the same timestamp');
 assert.equal(state.displayGraph.edges.filter(edge=>edge.target==='shared').length,1);
});
