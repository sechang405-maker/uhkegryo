import { projectNode } from './term-graph.mjs';

const clamp01=value=>Math.min(1,Math.max(0,value));
const smoothstep=value=>{const t=clamp01(value);return t*t*(3-2*t);};
const edgeKey=edge=>`${edge.source}:${edge.target}:${edge.relation||'category'}`;
const moved=(before,after)=>Boolean(before&&after)&&
  Math.hypot(before.x-after.x,before.y-after.y,before.z-after.z)>1e-6;
const interpolate=(from,to,amount)=>({
  x:from.x+(to.x-from.x)*amount,
  y:from.y+(to.y-from.y)*amount,
  z:from.z+(to.z-from.z)*amount,
});
const worldDistance=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y,a.z-b.z);

function pathProgress(path,amount) {
  const lengths=[];
  let total=0;
  for(let index=0;index<path.length-1;index++) {
    const length=worldDistance(path[index],path[index+1]);lengths.push(length);total+=length;
  }
  const target=total*clamp01(amount);
  let travelled=0,completedControls=0;
  for(let index=0;index<lengths.length;index++) {
    const next=travelled+lengths[index];
    if(index<path.length-2&&next<target-1e-9) completedControls=index+1;
    if(target<=next||index===lengths.length-1) {
      const local=lengths[index]?clamp01((target-travelled)/lengths[index]):0;
      return {point:interpolate(path[index],path[index+1],local),completedControls};
    }
    travelled=next;
  }
  return {point:path.at(-1),completedControls:Math.max(0,path.length-2)};
}

const motionProgress=(motion,now)=>motion.duration<=0?1:
  smoothstep(clamp01((now-motion.startedAt)/motion.duration));

export function motionAmount(motion,now) {
  if(!motion) return 1;
  const progress=motionProgress(motion,now);
  return motion.from+(motion.target-motion.from)*progress;
}

export function motionOpacity(motion,now) {
  if(!motion) return 1;
  const progress=motionProgress(motion,now);
  return motion.alphaFrom+(motion.alphaTo-motion.alphaFrom)*progress;
}

export function createGraphMotionState(graph,expandedIds=[]) {
  return {expandedIds:[...expandedIds],logicalGraph:graph,displayGraph:graph,presence:{}};
}

function transition({from,target,anchorId,originId,alphaFrom,alphaTo,now,duration}) {
  return {from,target,anchorId,originId,alphaFrom,alphaTo,startedAt:now,duration:Math.max(1,duration)};
}

function snapshot(oldNodes,presence,id,now) {
  const node=oldNodes.get(id),motion=presence[id];
  if(!node) return null;
  if(!motion) return {node,alpha:1};
  const anchor=oldNodes.get(motion.anchorId)||node;
  return {node:{...node,...interpolate(anchor,node,motionAmount(motion,now))},alpha:motionOpacity(motion,now)};
}

function addHelper(helpers,oldNodes,motion) {
  if(!motion?.originId||helpers.has(motion.originId)) return;
  const helper=oldNodes.get(motion.originId);
  if(helper) helpers.set(helper.id,helper);
}

export function reconcileGraphMotion(state,nextGraph,nextExpandedIds,anchorId,now,duration=260,reducedMotion=false) {
  if(reducedMotion||duration<=0) return createGraphMotionState(nextGraph,nextExpandedIds);
  const nextIds=new Set(nextGraph.nodes.map(node=>node.id));
  const oldNodes=new Map(state.displayGraph.nodes.map(node=>[node.id,node]));
  const presence={},helpers=new Map(),activeNodes=[];

  for(const node of nextGraph.nodes) {
    const oldNode=oldNodes.get(node.id),previous=state.presence[node.id];
    if(!oldNode) {
      presence[node.id]=transition({from:0,target:1,anchorId,alphaFrom:0,alphaTo:1,now,duration});
      activeNodes.push(node);
      continue;
    }
    if(previous?.target===1&&!moved(oldNode,node)) {
      presence[node.id]=previous;
      addHelper(helpers,oldNodes,previous);
      activeNodes.push(node);
      continue;
    }
    const current=snapshot(oldNodes,state.presence,node.id,now);
    if(previous||moved(current?.node,node)) {
      const originId=`motion-origin:${node.id}`;
      helpers.set(originId,{...current.node,id:originId,motionOrigin:true});
      presence[node.id]=transition({from:0,target:1,anchorId:originId,originId,
        alphaFrom:current.alpha,alphaTo:1,now,duration});
    }
    activeNodes.push(node);
  }

  const exitNodes=[];
  for(const [id,node] of oldNodes) {
    if(nextIds.has(id)||node.motionOrigin) continue;
    const previous=state.presence[id];
    if(previous?.target===0) {
      presence[id]=previous;
      addHelper(helpers,oldNodes,previous);
      exitNodes.push(node);
      continue;
    }
    const current=snapshot(oldNodes,state.presence,id,now);
    if(!current) continue;
    exitNodes.push({...current.node});
    presence[id]=transition({from:1,target:0,anchorId,alphaFrom:current.alpha,alphaTo:0,now,duration});
  }

  const displayNodes=[...activeNodes,...helpers.values(),...exitNodes];
  const exitingIds=new Set(Object.entries(presence).filter(([,motion])=>motion.target===0).map(([id])=>id));
  const logicalEdges=[...nextGraph.edges],logicalEdgeKeys=new Set(logicalEdges.map(edgeKey));
  const exitEdges=state.displayGraph.edges.filter(edge=>exitingIds.has(edge.target)&&!logicalEdgeKeys.has(edgeKey(edge)));
  return {
    expandedIds:[...nextExpandedIds],
    logicalGraph:nextGraph,
    displayGraph:{...nextGraph,nodes:displayNodes,edges:[...logicalEdges,...exitEdges]},
    presence,
  };
}

export function finishGraphMotion(state,now) {
  let changed=false;
  const presence={...state.presence},remove=new Set();
  for(const [id,motion] of Object.entries(state.presence)) {
    if(now<motion.startedAt+motion.duration) continue;
    changed=true;delete presence[id];
    if(motion.target===0) remove.add(id);
    if(motion.originId) remove.add(motion.originId);
  }
  if(!changed) return state;
  const nodes=state.displayGraph.nodes.filter(node=>!remove.has(node.id));
  const nodeIds=new Set(nodes.map(node=>node.id));
  const edges=state.displayGraph.edges.filter(edge=>nodeIds.has(edge.source)&&nodeIds.has(edge.target));
  return {...state,displayGraph:{...state.displayGraph,nodes,edges},presence};
}

export function pauseGraphMotion(state,elapsed) {
  if(!elapsed||elapsed<0||Object.keys(state.presence).length===0) return state;
  return {...state,presence:Object.fromEntries(Object.entries(state.presence).map(([id,motion])=>
    [id,{...motion,startedAt:motion.startedAt+elapsed}]))};
}

export function interpolateGraphMotion(displayGraph,presence,view,now) {
  const byId=new Map(displayGraph.nodes.map(node=>[node.id,node])),points={},amounts={},routeProgress={},
    routedEdgeByTarget=new Map(displayGraph.edges.filter(edge=>edge.relation&&edge.route?.length)
      .map(edge=>[edge.target,edge]));
  for(const node of displayGraph.nodes) {
    const motion=presence[node.id],amount=motionAmount(motion,now),anchor=byId.get(motion?.anchorId)||node;
    const routedEdge=routedEdgeByTarget.get(node.id),followsRoute=Boolean(motion&&routedEdge?.source===motion.anchorId),
      progress=followsRoute?pathProgress([anchor,...routedEdge.route,node],amount):null,
      world=motion?{...node,...(progress?.point||interpolate(anchor,node,amount))}:node;
    if(progress) routeProgress[edgeKey(routedEdge)]=progress;
    const point=projectNode(world,view),alpha=motionOpacity(motion,now);
    points[node.id]={...point,opacity:(point.opacity??1)*alpha,presence:amount};
    amounts[node.id]=amount;
  }
  const edgeRoutes={};
  for(const edge of displayGraph.edges) {
    if(!edge.route?.length) continue;
    const progress=routeProgress[edgeKey(edge)],visibleRoute=progress?
      edge.route.slice(0,progress.completedControls):edge.route;
    edgeRoutes[edgeKey(edge)]=visibleRoute.map(routePoint=>{
      const point=projectNode(routePoint,view);
      const opacity=points[edge.target]?.opacity??points[edge.source]?.opacity??1;
      return {...point,opacity};
    });
  }
  return {points,amounts,edgeRoutes};
}
