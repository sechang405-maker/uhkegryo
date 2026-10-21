import { createMindMapSlots } from './term-mind-map.mjs';

export const INITIAL_VIEW = Object.freeze({ yaw: -.32, pitch: .18, zoom: .9 });
export const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

export function buildTermGraph(terms) {
  const seen = new Set();
  const slots = createMindMapSlots(terms);
  const centers = [[-235,-135,140],[225,-135,-150],[230,145,150],[-225,145,-140]];
  const nodes = [], edges = [];
  slots.forEach((slot, index) => {
    const [x,y,z] = centers[index];
    const id = `category:${slot.role}`;
    nodes.push({id, label:slot.roleLabel, role:slot.role, x,y,z});
    slot.terms.forEach((term,i) => {
      if(seen.has(term.term_id)) return;
      seen.add(term.term_id);
      const angle = i * Math.PI * (3-Math.sqrt(5));
      const latitude = slot.terms.length > 1 ? 1 - 2 * i / (slot.terms.length-1) : 0;
      const radius = Math.sqrt(1-latitude*latitude);
      nodes.push({id:term.term_id,label:term.label_ko,role:slot.role,term,
        x:x+130*radius*Math.cos(angle),y:y+110*latitude,z:z+145*radius*Math.sin(angle)});
      edges.push({source:id,target:term.term_id});
    });
  });
  return {nodes,edges};
}

export function toggleExpanded(ids, id) {
  return ids.includes(id) ? ids.filter(value=>value!==id) : [...ids,id];
}

function relationshipIndex(terms) {
  const termsById=new Map(terms.map(term=>[term.term_id,term]));
  const childrenByParent=new Map();
  for(const term of terms) {
    for(const parentId of [...new Set([...(term.requires_all_of||[]),...(term.requires_any_of||[])])]) {
      if(!termsById.has(parentId)) continue;
      if(!childrenByParent.has(parentId)) childrenByParent.set(parentId,[]);
      childrenByParent.get(parentId).push(term.term_id);
    }
  }
  return {termsById,childrenByParent};
}

function stableAngle(id) {
  let hash=0;
  for(const character of id) hash=(hash*31+character.codePointAt(0))>>>0;
  return (hash%360)*Math.PI/180;
}

function spreadExpandedWorldLayout(nodes) {
  const width=1000,height=700,graph={nodes};
  const raw=projectGraph(graph,INITIAL_VIEW),positions=Object.fromEntries(Object.entries(raw).map(([id,point])=>[id,{...point}]));
  const items=nodes.map(node=>{
    const point=raw[node.id],visible=node.term&&point.depth>=-40;
    let boxWidth=!node.term?50:visible?Math.min(190,44+[...node.label].length*11):30;
    let boxHeight=!node.term?50:visible?42:30;
    if(node.expandable) {boxWidth+=40;boxHeight=Math.max(boxHeight,72);}
    const scale=node.term?Math.max(.72,point.scale):point.scale;
    return {node,halfWidth:boxWidth*scale/2*1000/width,halfHeight:boxHeight*scale/2*700/height,
      mobility:node.isDetail?1:node.term?(node.term.term_id.startsWith('pose_')?.7:.6):.25};
  });
  const gapX=8*1000/width,gapY=8*700/height;
  for(let iteration=0;iteration<180;iteration++) {
    if(iteration<120) for(const item of items) {
      const point=positions[item.node.id],origin=raw[item.node.id];
      point.x+=(origin.x-point.x)*.018;point.y+=(origin.y-point.y)*.018;
    }
    for(let first=0;first<items.length;first++) for(let second=first+1;second<items.length;second++) {
      const a=items[first],b=items[second],pa=positions[a.node.id],pb=positions[b.node.id];
      const dx=pb.x-pa.x,dy=pb.y-pa.y;
      const needX=a.halfWidth+b.halfWidth+gapX,needY=a.halfHeight+b.halfHeight+gapY;
      const overlapX=needX-Math.abs(dx),overlapY=needY-Math.abs(dy);
      if(overlapX<=0||overlapY<=0) continue;
      const total=a.mobility+b.mobility,shareA=a.mobility/total,shareB=b.mobility/total;
      if(overlapX/needX<overlapY/needY) {
        const direction=dx===0?(stableAngle(`${a.node.id}:${b.node.id}`)<Math.PI?1:-1):Math.sign(dx);
        pa.x-=direction*overlapX*shareA;pb.x+=direction*overlapX*shareB;
      } else {
        const direction=dy===0?(stableAngle(`${b.node.id}:${a.node.id}`)<Math.PI?1:-1):Math.sign(dy);
        pa.y-=direction*overlapY*shareA;pb.y+=direction*overlapY*shareB;
      }
    }
    for(const item of items) {
      const point=positions[item.node.id];
      point.x=clamp(point.x,item.halfWidth+gapX,1000-item.halfWidth-gapX);
      point.y=clamp(point.y,70+item.halfHeight+gapY,560-item.halfHeight-gapY);
    }
  }
  const right={x:Math.cos(INITIAL_VIEW.yaw),y:0,z:Math.sin(INITIAL_VIEW.yaw)};
  const up={x:Math.sin(INITIAL_VIEW.yaw)*Math.sin(INITIAL_VIEW.pitch),y:Math.cos(INITIAL_VIEW.pitch),
    z:-Math.cos(INITIAL_VIEW.yaw)*Math.sin(INITIAL_VIEW.pitch)};
  for(const node of nodes) {
    const origin=raw[node.id],point=positions[node.id];
    const perspective=1100/(1100-origin.depth),projectionScale=perspective*INITIAL_VIEW.zoom;
    const screenX=(point.x-origin.x)/projectionScale,screenY=(point.y-origin.y)/projectionScale;
    node.x+=right.x*screenX+up.x*screenY;
    node.y+=right.y*screenX+up.y*screenY;
    node.z+=right.z*screenX+up.z*screenY;
  }
}

export function buildExpandedTermGraph(baseTerms, catalogTerms, expandedIds=[]) {
  const base=buildTermGraph(baseTerms);
  const baseIds=new Set(baseTerms.map(term=>term.term_id));
  const expanded=new Set(expandedIds);
  const {termsById,childrenByParent}=relationshipIndex(catalogTerms);
  const visible=new Set(baseIds);
  const revealedChildren=new Set();
  const revealOrigin=new Map();
  let changed=true;
  while(changed) {
    changed=false;
    for(const parentId of [...visible]) {
      if(!expanded.has(parentId)) continue;
      for(const childId of childrenByParent.get(parentId)||[]) {
        revealedChildren.add(childId);
        if(!revealOrigin.has(childId)) revealOrigin.set(childId,parentId);
        const child=termsById.get(childId);
        for(const id of [childId,...(child?.requires_all_of||[]),...(child?.requires_any_of||[])]) {
          if(termsById.has(id)&&!visible.has(id)) {visible.add(id);changed=true;}
        }
      }
    }
  }

  const nodes=base.nodes.map(node=>node.term ? {...node,expandable:(childrenByParent.get(node.id)||[]).length>0} : node);
  const nodeById=new Map(nodes.map(node=>[node.id,node]));
  const categoryByRole=new Map(nodes.filter(node=>!node.term).map(node=>[node.role,node]));
  const makeNode=(term,anchor,angle,distance)=>({id:term.term_id,label:term.label_ko,role:term.role,term,isDetail:true,
    expandable:(childrenByParent.get(term.term_id)||[]).length>0,
    x:anchor.x+Math.cos(angle)*distance,y:anchor.y+Math.sin(angle)*distance*.78,
    z:anchor.z+Math.sin(angle*1.7)*distance*.72});
  const groups=new Map();
  for(const [childId,parentId] of revealOrigin) {
    if(baseIds.has(childId)) continue;
    if(!groups.has(parentId)) groups.set(parentId,[]);
    groups.get(parentId).push(childId);
  }
  let positioned=true;
  while(positioned) {
    positioned=false;
    for(const [parentId,childIds] of groups) {
      const anchor=nodeById.get(parentId);
      if(!anchor) continue;
      childIds.forEach((childId,index)=>{
        if(nodeById.has(childId)) return;
        const term=termsById.get(childId),ring=Math.floor(index/8),slot=index%8;
        const count=Math.min(8,childIds.length-ring*8),angle=stableAngle(parentId)+2*Math.PI*slot/count;
        const node=makeNode(term,anchor,angle,130+ring*78);
        nodes.push(node);nodeById.set(childId,node);positioned=true;
      });
    }
  }
  for(const term of catalogTerms) {
    if(!visible.has(term.term_id)||baseIds.has(term.term_id)||nodeById.has(term.term_id)) continue;
    const dependentNodes=[...revealedChildren].filter(childId=>{
      const child=termsById.get(childId);
      return [...(child?.requires_all_of||[]),...(child?.requires_any_of||[])].includes(term.term_id);
    }).map(id=>nodeById.get(id)).filter(Boolean);
    const anchor=dependentNodes.length ? {
      x:dependentNodes.reduce((sum,node)=>sum+node.x,0)/dependentNodes.length,
      y:dependentNodes.reduce((sum,node)=>sum+node.y,0)/dependentNodes.length,
      z:dependentNodes.reduce((sum,node)=>sum+node.z,0)/dependentNodes.length,
    } : categoryByRole.get(term.role)||{x:0,y:0,z:0};
    const node=makeNode(term,anchor,stableAngle(term.term_id),76);
    nodes.push(node);nodeById.set(node.id,node);
  }
  if(expanded.size>0) spreadExpandedWorldLayout(nodes);

  const edges=[...base.edges];
  const edgeKeys=new Set(edges.map(edge=>`${edge.source}:${edge.target}:category`));
  for(const childId of revealedChildren) {
    if(!visible.has(childId)) continue;
    const child=termsById.get(childId);
    for(const [relation,parents] of [['all',child?.requires_all_of||[]],['any',child?.requires_any_of||[]]]) {
      for(const parentId of parents) {
        if(!visible.has(parentId)) continue;
        const key=`${parentId}:${childId}:${relation}`;
        if(!edgeKeys.has(key)) {edges.push({source:parentId,target:childId,relation});edgeKeys.add(key);}
      }
    }
  }
  return {nodes,edges};
}

export function projectNode(node, view) {
  const x = node.x*Math.cos(view.yaw)+node.z*Math.sin(view.yaw);
  const z = -node.x*Math.sin(view.yaw)+node.z*Math.cos(view.yaw);
  const y = node.y*Math.cos(view.pitch)-z*Math.sin(view.pitch);
  const depth = node.y*Math.sin(view.pitch)+z*Math.cos(view.pitch);
  const perspective = 1100/(1100-depth);
  const zoom=clamp(view.zoom,.65,1.6);
  return {x:500+x*perspective*zoom,y:350+y*perspective*zoom,depth,scale:clamp(perspective,.65,1.6),
    opacity:clamp(.76+depth/1000,.42,1)};
}

export function toggleTerm(ids, id) {
  return ids.includes(id) ? ids.filter(value=>value!==id) : [...ids,id];
}

export function projectGraph(graph, view) {
  // Every visible anchor is derived from the same immutable world point and camera.
  return Object.fromEntries(graph.nodes.map(node=>[node.id,projectNode(node,view)]));
}

export function appendTerms(draft, terms) {
  let next=draft;
  for(const term of terms) {
    if(!next.includes(term.label_ko)) next += `${next && !/\s$/.test(next) ? ', ' : ''}${term.label_ko}`;
  }
  return [...next].length<=500 ? next : null;
}
