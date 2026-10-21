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

const vectorLength=vector=>Math.hypot(vector.x,vector.y,vector.z);
const unit=(vector,fallback={x:1,y:0,z:0})=>{
  const length=vectorLength(vector);
  return length>1e-8?{x:vector.x/length,y:vector.y/length,z:vector.z/length}:fallback;
};
const add=(a,b)=>({x:a.x+b.x,y:a.y+b.y,z:a.z+b.z});
const scale=(vector,amount)=>({x:vector.x*amount,y:vector.y*amount,z:vector.z*amount});
const dot=(a,b)=>a.x*b.x+a.y*b.y+a.z*b.z;
const cross=(a,b)=>({x:a.y*b.z-a.z*b.y,y:a.z*b.x-a.x*b.z,z:a.x*b.y-a.y*b.x});

function clampDirectionToCone(direction,axis,maxAngle=Math.PI/3-.04) {
  const from=unit(axis),to=unit(direction,from),angle=Math.acos(clamp(dot(from,to),-1,1));
  if(angle<=maxAngle) return to;
  const tangent=unit(add(to,scale(from,-dot(from,to))),{x:0,y:0,z:0});
  return unit(add(scale(from,Math.cos(maxAngle)),scale(tangent,Math.sin(maxAngle))),from);
}

function fanDirection(axis,categoryAxis,index,count,ring,key) {
  const outward=clampDirectionToCone(axis,categoryAxis,.66);
  const reference=Math.abs(outward.y)<.88?{x:0,y:1,z:0}:{x:1,y:0,z:0};
  const tangentA=unit(cross(outward,reference)),tangentB=unit(cross(outward,tangentA));
  const slots=Math.min(8,count-ring*8),slot=index%8;
  const azimuth=stableAngle(key)*.12+2*Math.PI*(slot+.5)/Math.max(1,slots);
  const deviation=count===1?.08:.22+ring*.035;
  const lateral=add(scale(tangentA,Math.cos(azimuth)),scale(tangentB,Math.sin(azimuth)));
  return clampDirectionToCone(add(scale(outward,Math.cos(deviation)),scale(lateral,Math.sin(deviation))),categoryAxis);
}

function arrangeOutwardWorldLayout(nodes,edges,revealOrigin) {
  const byId=new Map(nodes.map(node=>[node.id,node]));
  const categories=new Map(nodes.filter(node=>!node.term).map(node=>[node.role,node]));
  const relationParents=new Map(),relationChildren=new Map();
  for(const edge of edges.filter(edge=>edge.relation)) {
    if(!relationParents.has(edge.target)) relationParents.set(edge.target,[]);
    if(!relationChildren.has(edge.source)) relationChildren.set(edge.source,[]);
    relationParents.get(edge.target).push(edge.source);
    relationChildren.get(edge.source).push(edge.target);
  }
  const siblingGroups=new Map();
  for(const [childId,parentId] of revealOrigin) {
    if(!siblingGroups.has(parentId)) siblingGroups.set(parentId,[]);
    siblingGroups.get(parentId).push(childId);
  }
  for(const children of siblingGroups.values()) children.sort();
  const placed=new Set(nodes.filter(node=>!node.isDetail).map(node=>node.id)),placing=new Set();
  const setAt=(node,direction,radius)=>{
    const fixed=clampDirectionToCone(direction,categories.get(node.role)||direction);
    node.x=fixed.x*radius;node.y=fixed.y*radius;node.z=fixed.z*radius;placed.add(node.id);
  };
  const placePrimary=id=>{
    if(placed.has(id)) return true;
    const node=byId.get(id),primaryId=revealOrigin.get(id);
    if(!node||!primaryId||placing.has(id)) return false;
    placing.add(id);
    const primary=byId.get(primaryId);
    if(primary?.isDetail) placePrimary(primaryId);
    const parentNodes=(relationParents.get(id)||[]).map(parentId=>byId.get(parentId)).filter(parent=>parent&&placed.has(parent.id));
    if(primary&&placed.has(primary.id)&&!parentNodes.includes(primary)) parentNodes.push(primary);
    if(!parentNodes.length) {placing.delete(id);return false;}
    const categoryAxis=unit(categories.get(node.role)||primary),combined=parentNodes.reduce((sum,parent)=>add(sum,unit(parent)),scale(categoryAxis,.45));
    const siblings=siblingGroups.get(primaryId)||[id],index=Math.max(0,siblings.indexOf(id)),ring=Math.floor(index/8);
    const direction=fanDirection(combined,categoryAxis,index,siblings.length,ring,primaryId);
    const radius=Math.max(...parentNodes.map(vectorLength))+125+ring*82;
    setAt(node,direction,radius);placing.delete(id);return true;
  };
  for(let pass=0;pass<nodes.length;pass++) {
    let changed=false;
    for(const node of nodes.filter(node=>node.isDetail&&!placed.has(node.id))) if(placePrimary(node.id)) changed=true;
    if(!changed) break;
  }
  const supplemental=nodes.filter(node=>node.isDetail&&!placed.has(node.id)).sort((a,b)=>a.id.localeCompare(b.id));
  supplemental.forEach((node,index)=>{
    const category=categories.get(node.role)||{x:1,y:0,z:0},categoryAxis=unit(category);
    const dependents=(relationChildren.get(node.id)||[]).map(id=>byId.get(id)).filter(child=>child&&placed.has(child.id));
    const direction=dependents.length?dependents.reduce((sum,child)=>add(sum,unit(child)),scale(categoryAxis,.5)):categoryAxis;
    const outerRadius=dependents.length?Math.min(...dependents.map(vectorLength))-82:vectorLength(category)+90;
    setAt(node,fanDirection(direction,categoryAxis,index,supplemental.length,Math.floor(index/8),node.role),
      Math.max(vectorLength(category)+70,outerRadius));
  });
  // A shared child must remain beyond every visible parent. Primary hierarchy is
  // acyclic in reviewed data; supplemental parents are already placed inward.
  for(const edge of edges.filter(edge=>edge.relation)) {
    const parent=byId.get(edge.source),child=byId.get(edge.target);
    if(!parent||!child||!child.isDetail||placing.has(child.id)) continue;
    const needed=vectorLength(parent)+72;
    if(vectorLength(child)<needed) setAt(child,unit(child),needed);
  }
}

function separateInitialViewOverlaps(nodes,edges) {
  const categories=new Map(nodes.filter(node=>!node.term).map(node=>[node.role,node]));
  const minimumRadius=new Map(nodes.map(node=>[node.id,vectorLength(node)]));
  const raw=projectGraph({nodes},INITIAL_VIEW),positions=Object.fromEntries(Object.entries(raw).map(([id,point])=>[id,{...point}]));
  const items=nodes.map(node=>{
    const point=raw[node.id],visible=node.term&&point.depth>=-40;
    let width=!node.term?50:visible?Math.min(190,44+[...node.label].length*11):30;
    let height=!node.term?50:visible?42:30;
    const nodeScale=node.term?Math.max(.72,point.scale):point.scale;
    const anchorOffset=node.term&&visible?16:width/2;
    return {node,left:anchorOffset*nodeScale,right:(width-anchorOffset)*nodeScale,top:height*nodeScale/2,bottom:height*nodeScale/2,
      mobility:!node.term?0:node.isDetail?1:.55};
  });
  for(let iteration=0;iteration<220;iteration++) {
    let moved=false;
    for(let first=0;first<items.length;first++) for(let second=first+1;second<items.length;second++) {
      const a=items[first],b=items[second],pa=positions[a.node.id],pb=positions[b.node.id];
      const overlapX=Math.min(pa.x+a.right,pb.x+b.right)-Math.max(pa.x-a.left,pb.x-b.left)+8;
      const overlapY=Math.min(pa.y+a.bottom,pb.y+b.bottom)-Math.max(pa.y-a.top,pb.y-b.top)+8;
      if(overlapX<=0||overlapY<=0||a.mobility+b.mobility===0) continue;
      moved=true;
      const total=a.mobility+b.mobility,shareA=a.mobility/total,shareB=b.mobility/total;
      if(overlapX/(a.left+a.right+b.left+b.right)<overlapY/(a.top+a.bottom+b.top+b.bottom)) {
        const direction=pb.x===pa.x?(stableAngle(`${a.node.id}:${b.node.id}`)<Math.PI?1:-1):Math.sign(pb.x-pa.x);
        pa.x-=direction*overlapX*shareA;pb.x+=direction*overlapX*shareB;
      } else {
        const direction=pb.y===pa.y?(stableAngle(`${b.node.id}:${a.node.id}`)<Math.PI?1:-1):Math.sign(pb.y-pa.y);
        pa.y-=direction*overlapY*shareA;pb.y+=direction*overlapY*shareB;
      }
    }
    for(const item of items) if(item.node.term) {
      const point=positions[item.node.id];
      point.x=clamp(point.x,item.left+8,1000-item.right-8);
      point.y=clamp(point.y,70+item.top+8,650-item.bottom-8);
    }
    if(!moved) break;
  }
  const right={x:Math.cos(INITIAL_VIEW.yaw),y:0,z:Math.sin(INITIAL_VIEW.yaw)};
  const up={x:Math.sin(INITIAL_VIEW.yaw)*Math.sin(INITIAL_VIEW.pitch),y:Math.cos(INITIAL_VIEW.pitch),
    z:-Math.cos(INITIAL_VIEW.yaw)*Math.sin(INITIAL_VIEW.pitch)};
  for(const node of nodes.filter(node=>node.term)) {
    const origin=raw[node.id],point=positions[node.id],perspective=1100/(1100-origin.depth),projectionScale=perspective*INITIAL_VIEW.zoom;
    const screenX=(point.x-origin.x)/projectionScale,screenY=(point.y-origin.y)/projectionScale;
    const displaced={x:node.x+right.x*screenX+up.x*screenY,y:node.y+right.y*screenX+up.y*screenY,z:node.z+right.z*screenX+up.z*screenY};
    const direction=clampDirectionToCone(displaced,categories.get(node.role)||displaced);
    const radius=Math.max(minimumRadius.get(node.id),vectorLength(displaced));
    node.x=direction.x*radius;node.y=direction.y*radius;node.z=direction.z*radius;
  }
  const byId=new Map(nodes.map(node=>[node.id,node]));
  for(const edge of edges.filter(edge=>edge.relation)) {
    const parent=byId.get(edge.source),child=byId.get(edge.target);
    if(!parent||!child||!child.isDetail) continue;
    const needed=vectorLength(parent)+72;
    if(vectorLength(child)<needed) {
      const direction=unit(child);child.x=direction.x*needed;child.y=direction.y*needed;child.z=direction.z*needed;
    }
  }
  // Resolve any overlap reintroduced by cone/radius constraints by moving the
  // farther item only farther outward. This never pulls a branch across center.
  for(let iteration=0;iteration<240;iteration++) {
    const projected=projectGraph({nodes},INITIAL_VIEW);
    const visible=nodes.filter(node=>node.term&&projected[node.id].depth>=-40).map(node=>{
      const point=projected[node.id],nodeScale=Math.max(.72,point.scale);
      const width=Math.min(190,44+[...node.label].length*11),anchorOffset=16*nodeScale;
      return {node,point,left:anchorOffset,right:width*nodeScale-anchorOffset,top:21*nodeScale,bottom:21*nodeScale};
    });
    let overlap=null;
    for(let first=0;first<visible.length&&!overlap;first++) for(let second=first+1;second<visible.length;second++) {
      const a=visible[first],b=visible[second],overlapX=Math.min(a.point.x+a.right,b.point.x+b.right)-Math.max(a.point.x-a.left,b.point.x-b.left),
        overlapY=Math.min(a.point.y+a.bottom,b.point.y+b.bottom)-Math.max(a.point.y-a.top,b.point.y-b.top);
      if(overlapX>0&&overlapY>0) {overlap={a,b,amount:Math.min(overlapX,overlapY)+5};break;}
    }
    if(!overlap) break;
    const screenRadius=item=>Math.hypot(item.point.x-500,item.point.y-350);
    const mover=screenRadius(overlap.a)>=screenRadius(overlap.b)?overlap.a:overlap.b;
    const dx=mover.point.x-500,dy=mover.point.y-350,length=Math.hypot(dx,dy)||1;
    const perspective=1100/(1100-mover.point.depth),projectionScale=perspective*INITIAL_VIEW.zoom;
    const worldStep=overlap.amount/projectionScale;
    const displaced=add(mover.node,add(scale(right,dx/length*worldStep),scale(up,dy/length*worldStep)));
    const direction=mover.node.isDetail?clampDirectionToCone(displaced,categories.get(mover.node.role)||displaced):unit(displaced);
    const radius=Math.max(vectorLength(mover.node),vectorLength(displaced));
    mover.node.x=direction.x*radius;mover.node.y=direction.y*radius;mover.node.z=direction.z*radius;
  }
}

export function buildExpandedTermGraph(baseTerms, catalogTerms, expandedIds=[]) {
  const base=buildTermGraph(baseTerms);
  const baseIds=new Set(baseTerms.map(term=>term.term_id));
  const expandedOrder=[...new Set(expandedIds)],expanded=new Set(expandedOrder);
  const {termsById,childrenByParent}=relationshipIndex(catalogTerms);
  const visible=new Set(baseIds);
  const revealedChildren=new Set();
  const revealOrigin=new Map();
  let changed=true;
  while(changed) {
    changed=false;
    for(const parentId of expandedOrder) {
      if(!visible.has(parentId)) continue;
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
  const relationships=[];
  const relationshipKeys=new Set();
  for(const childId of revealedChildren) {
    if(!visible.has(childId)) continue;
    const child=termsById.get(childId);
    for(const [relation,parents] of [['all',child?.requires_all_of||[]],['any',child?.requires_any_of||[]]]) {
      for(const parentId of parents) {
        if(!visible.has(parentId)) continue;
        const key=`${parentId}:${childId}:${relation}`;
        if(!relationshipKeys.has(key)) {relationships.push({source:parentId,target:childId,relation});relationshipKeys.add(key);}
      }
    }
  }
  const edges=[...base.edges];
  for(const node of nodes.filter(node=>node.isDetail)) {
    const candidates=relationships.filter(edge=>edge.target===node.id);
    const preferred=revealOrigin.get(node.id);
    const representative=candidates.find(edge=>edge.source===preferred)||candidates[0];
    if(representative) edges.push(representative);
    else {
      const category=categoryByRole.get(node.role);
      if(category) edges.push({source:category.id,target:node.id});
    }
  }
  if(expanded.size>0) {
    arrangeOutwardWorldLayout(nodes,edges,revealOrigin);
    separateInitialViewOverlaps(nodes,edges);
  }
  return {nodes,edges,relationships};
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
