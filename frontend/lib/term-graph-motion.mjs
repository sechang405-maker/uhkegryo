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
  const byId=new Map(displayGraph.nodes.map(node=>[node.id,node])),points={},amounts={};
  for(const node of displayGraph.nodes) {
    const motion=presence[node.id],amount=motionAmount(motion,now),anchor=byId.get(motion?.anchorId)||node;
    const world=motion?{...node,...interpolate(anchor,node,amount)}:node;
    const point=projectNode(world,view),alpha=motionOpacity(motion,now);
    points[node.id]={...point,opacity:(point.opacity??1)*alpha,presence:amount};
    amounts[node.id]=amount;
  }
  return {points,amounts};
}
