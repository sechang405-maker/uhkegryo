import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildGraphDepthLayers,
  perspectiveDepthAt,
} from '../lib/term-graph-edges.mjs';

const point=(x,y,depth,opacity=1)=>({x,y,depth,opacity});
const node=(id,depth)=>({id,term:{term_id:id},motionOrigin:false,depth});

test('screen-space edge depth uses perspective-correct reciprocal interpolation',()=>{
  assert.ok(Math.abs(perspectiveDepthAt(-500,500,.5)-227.2727272727)<1e-8);
  assert.equal(perspectiveDepthAt(-500,500,0),-500);
  assert.equal(perspectiveDepthAt(-500,500,1),500);
});

test('one projected edge is interleaved on both sides of different node depths',()=>{
  const nodes=[node('source',-500),node('rear',-200),node('front',350),node('target',500)];
  const points={
    source:point(100,200,-500),rear:point(400,400,-200),front:point(600,400,350),target:point(900,200,500),
  };
  const result=buildGraphDepthLayers(nodes,[{source:'source',target:'target',relation:'all'}],points,{endpointTrim:0});
  const segments=result.layers.flatMap(layer=>layer.segments.map(segment=>({...segment,zIndex:layer.zIndex})));
  const behindRear=segments.find(segment=>segment.depth<-200);
  const between=segments.find(segment=>segment.depth>-200&&segment.depth<350);
  assert.ok(behindRear.zIndex<result.nodeZ.rear,'edge behind the rear node before its depth crossing');
  assert.ok(between.zIndex>result.nodeZ.rear,'same edge in front of the rear node after crossing');
  assert.ok(between.zIndex<result.nodeZ.front,'same edge remains behind the front node');
});

test('endpoint fragments remain below their own node while the middle keeps depth order',()=>{
  const nodes=[node('source',-300),node('crossed',0),node('target',400)];
  const points={source:point(100,200,-300),crossed:point(500,200,0),target:point(900,200,400)};
  const result=buildGraphDepthLayers(nodes,[{source:'source',target:'target',relation:'any'}],points,{endpointTrim:64});
  const segments=result.layers.flatMap(layer=>layer.segments.map(segment=>({...segment,zIndex:layer.zIndex})));
  const sourceFragment=segments.find(segment=>segment.endpoint==='source');
  const targetFragment=segments.find(segment=>segment.endpoint==='target');
  assert.ok(sourceFragment.zIndex<result.nodeZ.source);
  assert.ok(targetFragment.zIndex<result.nodeZ.target);
  assert.equal(Math.abs(sourceFragment.dashOffset),0);
  assert.ok(targetFragment.dashOffset>0,'dash phase advances continuously across split segments');
});

test('every depth split inside an endpoint footprint remains under its owner',()=>{
  const nodes=[node('source',-500),node('near-source-cut',-490),node('target',500)];
  const points={source:point(100,200,-500),'near-source-cut':point(500,500,-490),target:point(900,200,500)};
  const result=buildGraphDepthLayers(nodes,[{source:'source',target:'target'}],points,{endpointTrim:64});
  const segments=result.layers.flatMap(layer=>layer.segments.map(segment=>({...segment,zIndex:layer.zIndex})));
  const sourceFootprint=segments.filter(segment=>segment.t1<=.08+1e-7);
  assert(sourceFootprint.length>1,'fixture must split inside the source footprint');
  assert(sourceFootprint.every(segment=>segment.zIndex<result.nodeZ.source),'a depth cut escaped above its endpoint owner');
});

test('near-equal depths still create the perspective crossing plane',()=>{
  const nodes=[node('source',0),node('middle',.05),node('target',.1)];
  const points={source:point(0,0,0),middle:point(500,300,.05),target:point(1000,0,.1)};
  const result=buildGraphDepthLayers(nodes,[{source:'source',target:'target'}],points,{endpointTrim:0});
  const segments=result.layers.flatMap(layer=>layer.segments.map(segment=>({...segment,zIndex:layer.zIndex})));
  assert.equal(segments.length,2,'small but real camera-depth span was treated as flat');
  assert.ok(segments[0].zIndex<result.nodeZ.middle);
  assert.ok(segments[1].zIndex>result.nodeZ.middle);
});

test('overlapping endpoint footprints keep their shared region below both nodes',()=>{
  const cutDepth=perspectiveDepthAt(500,-500,.45);
  const nodes=[node('source',500),node('depth-cut',cutDepth),node('target',-500)];
  const points={source:point(0,0,500),'depth-cut':point(50,80,cutDepth),target:point(100,0,-500)};
  const result=buildGraphDepthLayers(nodes,[{source:'source',target:'target'}],points,{endpointTrim:64});
  const segments=result.layers.flatMap(layer=>layer.segments.map(segment=>({...segment,zIndex:layer.zIndex})));
  const shared=segments.filter(segment=>(segment.t0+segment.t1)/2>.36&&(segment.t0+segment.t1)/2<.64);
  assert(shared.length>0,'fixture must contain a segment inside both endpoint circles');
  assert(shared.every(segment=>segment.zIndex<result.nodeZ.source&&segment.zIndex<result.nodeZ.target),
    'overlapping endpoint masks did not both apply');
});

test('motion origin helpers do not create visible depth planes',()=>{
  const nodes=[node('source',-100),{...node('helper',0),motionOrigin:true},node('target',100)];
  const points={source:point(0,0,-100),helper:point(50,0,0),target:point(100,0,100)};
  const result=buildGraphDepthLayers(nodes,[{source:'source',target:'target'}],points,{endpointTrim:0});
  assert.equal(result.nodeZ.helper,undefined);
  assert.equal(result.layers.flatMap(layer=>layer.segments).length,1);
});

test('near-equal depth clustering never leaves a visible node without a layer',()=>{
  const nodes=[node('a',0),node('b',.75e-7),node('c',1.5e-7)];
  const points={a:point(0,0,0),b:point(10,0,.75e-7),c:point(20,0,1.5e-7)};
  const result=buildGraphDepthLayers(nodes,[],points);
  assert.deepEqual(Object.keys(result.nodeZ).sort(),['a','b','c']);
  assert.ok(Object.values(result.nodeZ).every(z=>Number.isInteger(z)&&z>=2));
});
