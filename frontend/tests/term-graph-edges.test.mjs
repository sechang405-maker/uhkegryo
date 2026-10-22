import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildGraphDepthLayers,
  perspectiveDepthAt,
} from '../lib/term-graph-edges.mjs';
import { projectNode } from '../lib/term-graph.mjs';

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

test('a front edge remains visible while crossing an unrelated rear term node',()=>{
  const nodes=[node('source',200),node('crossed',-200),node('target',200)];
  const points={source:point(100,200,200),crossed:point(500,200,-200),target:point(900,200,200)};
  for(const viewport of [{width:1000,height:840},{width:1474,height:680},{width:760,height:480}]) {
    const result=buildGraphDepthLayers(nodes,[{source:'source',target:'target',relation:'all'}],points,{endpointTrim:0,viewport});
    const segments=result.layers.flatMap(layer=>layer.segments.map(segment=>({...segment,zIndex:layer.zIndex})));
    assert.ok(segments.some(segment=>segment.zIndex>result.nodeZ.crossed),'the whole connector was incorrectly sent behind');
    assert.ok(segments.some(segment=>segment.x1<500&&segment.x2>500),
      `the front connector disappeared inside the rear circle at ${viewport.width}x${viewport.height}`);
  }
});

test('a rear edge stays below unrelated front term and category nodes',()=>{
  const category={id:'category',role:'category',motionOrigin:false};
  const nodes=[node('source',-200),node('term',200),category,node('target',-200)];
  const points={source:point(100,200,-200),term:point(400,200,200),category:point(600,200,200),target:point(900,200,-200)};
  const result=buildGraphDepthLayers(nodes,[{source:'source',target:'target',relation:'all'}],points,
    {endpointTrim:0,viewport:{width:1000,height:840}});
  const segments=result.layers.flatMap(layer=>layer.segments.map(segment=>({...segment,zIndex:layer.zIndex})));
  assert.ok(segments.some(segment=>segment.x1<400&&segment.x2>400),'the straight edge was incorrectly clipped at the term');
  assert.ok(segments.some(segment=>segment.x1<600&&segment.x2>600),'the straight edge was incorrectly clipped at the category');
  assert.ok(segments.every(segment=>segment.zIndex<result.nodeZ.term&&segment.zIndex<result.nodeZ.category),
    'the rear edge escaped above a front node');
});

test('an edge crossing a node depth inside its circle changes painter order at the crossing',()=>{
  const cutT=(1/1100-1/1600)/(1/600-1/1600),crossingX=100+800*cutT;
  const nodes=[node('source',-500),node('crossed',0),node('target',500)];
  const points={source:point(100,200,-500),crossed:point(crossingX,200,0),target:point(900,200,500)};
  const result=buildGraphDepthLayers(nodes,[{source:'source',target:'target',relation:'all'}],points,{endpointTrim:0});
  const segments=result.layers.flatMap(layer=>layer.segments.map(segment=>({...segment,zIndex:layer.zIndex})));
  const rear=segments.find(segment=>segment.x2<=crossingX+1e-6&&segment.x2>crossingX-40);
  const front=segments.find(segment=>segment.x1>=crossingX-1e-6&&segment.x1<crossingX+40);
  assert.ok(rear&&rear.zIndex<result.nodeZ.crossed,'the rear half did not stay below the node');
  assert.ok(front&&front.zIndex>result.nodeZ.crossed,'the front half did not rise above the node');
});

test('straight edge painter order follows yaw, pitch, and zoom without changing world points',()=>{
  const source={id:'source',term:{term_id:'source'},motionOrigin:false,x:-300,y:0,z:120};
  const target={id:'target',term:{term_id:'target'},motionOrigin:false,x:300,y:0,z:120};
  const crossed={id:'crossed',role:'pose',motionOrigin:false,x:0,y:0,z:0};
  const nodes=[source,crossed,target],edge={source:'source',target:'target',relation:'all'},
    world=nodes.map(({x,y,z})=>({x,y,z}));
  for(const view of [
    {yaw:0,pitch:0,zoom:.65},
    {yaw:0,pitch:0,zoom:1.25},
    {yaw:Math.PI,pitch:0,zoom:.9},
  ]) {
    const points=Object.fromEntries(nodes.map(item=>[item.id,projectNode(item,view)])),
      result=buildGraphDepthLayers(nodes,[edge],points,{endpointTrim:0}),
      segments=result.layers.flatMap(layer=>layer.segments.map(segment=>({...segment,zIndex:layer.zIndex}))),
      edgeIsFront=points.source.depth>points.crossed.depth;
    assert.ok(segments.every(segment=>edgeIsFront?
      segment.zIndex>result.nodeZ.crossed:segment.zIndex<result.nodeZ.crossed));
  }
  const verticalSource={...source,x:-300,y:120,z:0},verticalTarget={...target,x:300,y:120,z:0};
  for(const pitch of [-.6,.6]) {
    const verticalNodes=[verticalSource,crossed,verticalTarget],view={yaw:0,pitch,zoom:.9},
      points=Object.fromEntries(verticalNodes.map(item=>[item.id,projectNode(item,view)])),
      result=buildGraphDepthLayers(verticalNodes,[edge],points,{endpointTrim:0}),
      segments=result.layers.flatMap(layer=>layer.segments.map(segment=>({...segment,zIndex:layer.zIndex}))),
      edgeIsFront=points.source.depth>points.crossed.depth;
    assert.ok(segments.every(segment=>edgeIsFront?
      segment.zIndex>result.nodeZ.crossed:segment.zIndex<result.nodeZ.crossed));
  }
  assert.deepEqual(nodes.map(({x,y,z})=>({x,y,z})),world);
});

test('near-equal depth clustering never leaves a visible node without a layer',()=>{
  const nodes=[node('a',0),node('b',.75e-7),node('c',1.5e-7)];
  const points={a:point(0,0,0),b:point(10,0,.75e-7),c:point(20,0,1.5e-7)};
  const result=buildGraphDepthLayers(nodes,[],points);
  assert.deepEqual(Object.keys(result.nodeZ).sort(),['a','b','c']);
  assert.ok(Object.values(result.nodeZ).every(z=>Number.isInteger(z)&&z>=2));
});
