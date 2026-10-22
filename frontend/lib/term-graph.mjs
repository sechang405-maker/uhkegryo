import { createMindMapSlots } from './term-mind-map.mjs';
import { approvedCatalogWorldLayout } from './term-graph-approved-layout.mjs';

export const INITIAL_VIEW = Object.freeze({ yaw: -.32, pitch: .18, zoom: .9 });
export const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

const INITIAL_FRAME = Object.freeze({x:500,y:480});
const GRAPH_CENTER = Object.freeze({x:500,y:420});
const CATEGORY_ANGLE = Object.freeze({
  body:-3*Math.PI/4,
  pose:-Math.PI/4,
  composition:Math.PI/4,
  perspective:3*Math.PI/4,
});

function worldFromInitialProjection(screenX,screenY,depth) {
  const perspective=1100/(1100-depth),factor=perspective*INITIAL_VIEW.zoom;
  const cameraX=(screenX-INITIAL_FRAME.x)/factor,cameraY=(screenY-INITIAL_FRAME.y)/factor;
  const worldY=cameraY*Math.cos(INITIAL_VIEW.pitch)+depth*Math.sin(INITIAL_VIEW.pitch);
  const yawZ=-cameraY*Math.sin(INITIAL_VIEW.pitch)+depth*Math.cos(INITIAL_VIEW.pitch);
  return {
    x:cameraX*Math.cos(INITIAL_VIEW.yaw)-yawZ*Math.sin(INITIAL_VIEW.yaw),
    y:worldY,
    z:cameraX*Math.sin(INITIAL_VIEW.yaw)+yawZ*Math.cos(INITIAL_VIEW.yaw),
  };
}

export function buildTermGraph(terms, childCounts=new Map()) {
  const seen = new Set();
  const slots = createMindMapSlots(terms);
  const nodes = [], edges = [];
  slots.forEach((slot, index) => {
    const angle=CATEGORY_ANGLE[slot.role]??(-3*Math.PI/4+index*Math.PI/2);
    const categoryScreen={x:GRAPH_CENTER.x+128*Math.cos(angle),y:GRAPH_CENTER.y+128*Math.sin(angle)};
    const categoryDepth=index%2?-160:160;
    const {x,y,z}=worldFromInitialProjection(categoryScreen.x,categoryScreen.y,categoryDepth);
    const id = `category:${slot.role}`;
    const category={id,label:slot.roleLabel,role:slot.role,x,y,z};
    nodes.push(category);
    const visualOrder=[...slot.terms].sort((a,b)=>(childCounts.get(b.term_id)||0)-(childCounts.get(a.term_id)||0)||
      slot.terms.indexOf(a)-slot.terms.indexOf(b));
    const priorityCount=visualOrder.filter(term=>(childCounts.get(term.term_id)||0)>0).length;
    slot.terms.forEach((term,i) => {
      if(seen.has(term.term_id)) return;
      seen.add(term.term_id);
      const visualIndex=visualOrder.findIndex(candidate=>candidate.term_id===term.term_id);
      // Four deterministic lanes fill the role's quadrant without collapsing
      // every label onto one narrow arc. Expandable roots are sorted first, so
      // their outward child territory remains close to the hub.
      let screen;
      if(priorityCount>0&&visualIndex<priorityCount) {
        const priorityOffsets=[.14,-.36,.62,-.62,.4,-.12,0],offset=priorityOffsets[visualIndex]??0,
          radial=230+Math.floor(visualIndex/3)*60+(stableAngle(term.term_id)/(2*Math.PI)-.5)*6;
        screen={x:GRAPH_CENTER.x+radial*Math.cos(angle+offset),y:GRAPH_CENTER.y+radial*Math.sin(angle+offset)};
      } else {
        const restIndex=priorityCount>0?visualIndex-priorityCount:visualIndex,perRing=priorityCount>0?3:4,
          ring=Math.floor(restIndex/perRing),slotIndex=restIndex%perRing,
          slotsInRing=Math.min(perRing,slot.terms.length-(priorityCount>0?priorityCount:0)-ring*perRing);
        if(priorityCount>0) {
          const radial=250+ring*90+(stableAngle(term.term_id)/(2*Math.PI)-.5)*8,
            offset=.82+(slotIndex-(slotsInRing-1)/2)*.18;
          screen={x:GRAPH_CENTER.x+radial*Math.cos(angle+offset),y:GRAPH_CENTER.y+radial*Math.sin(angle+offset)};
        } else {
          const radial=180+ring*80+(stableAngle(term.term_id)/(2*Math.PI)-.5)*8,
            lateral=(slotIndex-(slotsInRing-1)/2)*80;
          screen={x:GRAPH_CENTER.x+radial*Math.cos(angle)-lateral*Math.sin(angle),
            y:GRAPH_CENTER.y+radial*Math.sin(angle)+lateral*Math.cos(angle)};
        }
      }
      const depthBand=[-100,-50,0,50,100][i%5],roleDepth=index%2?-160:160;
      const point=worldFromInitialProjection(screen.x,screen.y,depthBand+roleDepth);
      nodes.push({id:term.term_id,label:term.label_ko,role:slot.role,term,childCount:childCounts.get(term.term_id)||0,
        x:point.x,y:point.y,z:point.z});
      edges.push({source:id,target:term.term_id});
    });
  });
  separateBaseCircleOverlaps(nodes);
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

// Deliberately reserve a little more than the rendered circle. The buffer is
// what keeps 14px labels and the integrated control readable after projection.
const nodeCircleRadius=node=>node.isDetail?(node.expandable?56:48):(node.childCount>0?52:44);
const renderedCircleRadius=node=>node.isDetail?(node.expandable?48:40):(node.childCount>0?46:38);
const GRAPH_PANEL_Y_SCALE=680/840;
const screenCircleDistance=(first,second)=>Math.hypot(first.x-second.x,(first.y-second.y)*GRAPH_PANEL_Y_SCALE);
const stabilizedLayoutCache=new WeakMap();
// A single full-catalog world layout reserves every branch before expansion.
// Synthetic/unknown catalogs continue through the bounded fallback below.
const ACTIVE_CATALOG_LAYOUT=approvedCatalogWorldLayout(INITIAL_VIEW);
const screenDelta=(first,second)=>{
  const dx=second.x-first.x,dy=(second.y-first.y)*GRAPH_PANEL_Y_SCALE;
  return {dx,dy,distance:Math.hypot(dx,dy)||1};
};

function straightEdgeDistance(start,end,obstacle) {
  const sx=start.x,sy=start.y*GRAPH_PANEL_Y_SCALE,ex=end.x,ey=end.y*GRAPH_PANEL_Y_SCALE,
    ox=obstacle.x,oy=obstacle.y*GRAPH_PANEL_Y_SCALE,dx=ex-sx,dy=ey-sy,lengthSquared=dx*dx+dy*dy,
    amount=lengthSquared?clamp(((ox-sx)*dx+(oy-sy)*dy)/lengthSquared,0,1):0;
  return Math.hypot(ox-(sx+dx*amount),oy-(sy+dy*amount));
}

function straightEdgeClearance(start,end,obstacle) {
  const sx=start.x,sy=start.y*GRAPH_PANEL_Y_SCALE,ex=end.x,ey=end.y*GRAPH_PANEL_Y_SCALE,
    ox=obstacle.x,oy=obstacle.y*GRAPH_PANEL_Y_SCALE,dx=ex-sx,dy=ey-sy,lengthSquared=dx*dx+dy*dy,
    amount=lengthSquared?clamp(((ox-sx)*dx+(oy-sy)*dy)/lengthSquared,0,1):0;
  return {distance:Math.hypot(ox-(sx+dx*amount),oy-(sy+dy*amount)),amount};
}

function straightLayoutIsUnsafe(nodes,edges) {
  const projected=projectGraph({nodes},INITIAL_VIEW);
  for(let first=0;first<nodes.length;first++) for(let second=first+1;second<nodes.length;second++) {
    const a=nodes[first],b=nodes[second],pa=projected[a.id],pb=projected[b.id];
    if(!pa||!pb) continue;
    if(screenCircleDistance(pa,pb)<renderedCircleRadius(a)+renderedCircleRadius(b)+.5) return true;
  }
  for(const edge of edges.filter(edge=>edge.relation)) {
    const source=projected[edge.source],target=projected[edge.target];
    if(!source||!target) continue;
    for(const obstacleNode of nodes.filter(node=>node.id!==edge.source&&node.id!==edge.target)) {
      const obstacle=projected[obstacleNode.id];
      if(!obstacle) continue;
      const hit=straightEdgeClearance(source,target,obstacle);
      if(hit.amount>.01&&hit.amount<.99&&hit.distance<renderedCircleRadius(obstacleNode)+2) return true;
    }
  }
  return false;
}

function separateBaseCircleOverlaps(nodes) {
  const terms=nodes.filter(node=>node.term),projected=projectGraph({nodes},INITIAL_VIEW),
    positions=new Map(terms.map(node=>[node.id,{x:projected[node.id].x,y:projected[node.id].y,depth:projected[node.id].depth}])),
    categoryByRole=new Map(nodes.filter(node=>!node.term).map(node=>[node.role,node])),
    denseRoots=new Set(terms.filter(node=>node.childCount>=4).map(node=>node.id));
  for(let iteration=0;iteration<180;iteration++) {
    let moved=false;
    for(let first=0;first<terms.length;first++) for(let second=first+1;second<terms.length;second++) {
      const a=terms[first],b=terms[second],pa=positions.get(a.id),pb=positions.get(b.id),{dx,dy,distance}=screenDelta(pa,pb),
        territoryA=nodeCircleRadius(a)+Math.min(48,Math.sqrt(a.childCount||0)*18),
        territoryB=nodeCircleRadius(b)+Math.min(48,Math.sqrt(b.childCount||0)*18),
        needed=territoryA+territoryB+12-distance;
      if(needed<=0) continue;
      moved=true;
      const ux=dx/distance,uy=dy/distance,sign=distance===1&&dx===0&&dy===0?(stableAngle(`${a.id}:${b.id}`)<Math.PI?1:-1):1,
        aFixed=denseRoots.has(a.id),bFixed=denseRoots.has(b.id);
      if(aFixed&&!bFixed) {pb.x+=ux*needed*sign;pb.y+=uy*needed*sign/GRAPH_PANEL_Y_SCALE;}
      else if(bFixed&&!aFixed) {pa.x-=ux*needed*sign;pa.y-=uy*needed*sign/GRAPH_PANEL_Y_SCALE;}
      else if(!aFixed&&!bFixed) {
        pa.x-=ux*needed*.5*sign;pa.y-=uy*needed*.5*sign/GRAPH_PANEL_Y_SCALE;
        pb.x+=ux*needed*.5*sign;pb.y+=uy*needed*.5*sign/GRAPH_PANEL_Y_SCALE;
      }
    }
    for(const node of terms) {
      const point=positions.get(node.id),radius=nodeCircleRadius(node);
      point.x=clamp(point.x,radius+14,1000-radius-14);point.y=clamp(point.y,radius+64,800-radius);
    }
    if(!moved) break;
  }
  // Dense branch roots retain their category-lane radius. Pulling them toward
  // the center placed the parent on top of its category hub, so every outward
  // straight connector began inside an unrelated circle.
  for(let iteration=0;iteration<80;iteration++) for(let first=0;first<terms.length;first++) for(let second=first+1;second<terms.length;second++) {
    const a=terms[first],b=terms[second],pa=positions.get(a.id),pb=positions.get(b.id),{dx,dy,distance}=screenDelta(pa,pb),
      needed=nodeCircleRadius(a)+nodeCircleRadius(b)+12-distance;
    if(needed<=0) continue;
    const ux=dx/distance,uy=dy/distance,aFixed=denseRoots.has(a.id),bFixed=denseRoots.has(b.id);
    if(aFixed&&!bFixed) {pb.x+=ux*needed;pb.y+=uy*needed/GRAPH_PANEL_Y_SCALE;}
    else if(bFixed&&!aFixed) {pa.x-=ux*needed;pa.y-=uy*needed/GRAPH_PANEL_Y_SCALE;}
    else {pa.x-=ux*needed*.5;pa.y-=uy*needed*.5/GRAPH_PANEL_Y_SCALE;
      pb.x+=ux*needed*.5;pb.y+=uy*needed*.5/GRAPH_PANEL_Y_SCALE;}
    for(const node of [a,b]) {
      const point=positions.get(node.id),radius=nodeCircleRadius(node);
      point.x=clamp(point.x,radius+14,1000-radius-14);point.y=clamp(point.y,radius+64,800-radius);
    }
  }
  // Solve branch landing zones and base-circle separation together. A former
  // one-way landing pass cleared the corridor but created fresh base overlaps;
  // alternating both constraints converges without moving roots on expand.
  for(let iteration=0;iteration<96;iteration++) {
    for(const parent of terms.filter(node=>node.childCount>0)) {
      const origin=positions.get(parent.id),dx=origin.x-GRAPH_CENTER.x,dy=origin.y-GRAPH_CENTER.y,length=Math.hypot(dx,dy)||1,
        angle=Math.atan2(dy,dx),dense=parent.childCount>=4,zones=[];
      if(dense) {
        const rings=Math.ceil(parent.childCount/4),half=.78,bias=Math.sin(angle)<0?.18:-.18;
        for(let ring=0;ring<rings;ring++) {
          const slots=Math.min(4,parent.childCount-ring*4);
          for(let slot=0;slot<slots;slot++) {
            const fraction=slots===1?0:(slot-(slots-1)/2)/((slots-1)/2),zoneAngle=angle+bias+fraction*half,
              zoneRadius=length+116+ring*104;
            zones.push({x:GRAPH_CENTER.x+Math.cos(zoneAngle)*zoneRadius,y:GRAPH_CENTER.y+Math.sin(zoneAngle)*zoneRadius,radius:68});
          }
        }
      } else zones.push({x:origin.x+dx/length*145,y:origin.y+dy/length*145,radius:58});
      for(const zone of zones) for(const node of terms) {
        if(node.id===parent.id) continue;
        const point=positions.get(node.id),vx=point.x-zone.x,vy=(point.y-zone.y)*GRAPH_PANEL_Y_SCALE,distance=Math.hypot(vx,vy)||1,
          needed=nodeCircleRadius(node)+zone.radius-distance;
        if(needed>0) {point.x+=vx/distance*needed;point.y+=vy/distance*needed/GRAPH_PANEL_Y_SCALE;}
      }
    }
    for(let first=0;first<terms.length;first++) for(let second=first+1;second<terms.length;second++) {
      const a=terms[first],b=terms[second],pa=positions.get(a.id),pb=positions.get(b.id),{dx,dy,distance}=screenDelta(pa,pb),
        needed=nodeCircleRadius(a)+nodeCircleRadius(b)+12-distance;
      if(needed<=0) continue;
      const ux=dx/distance,uy=dy/distance,aFixed=denseRoots.has(a.id),bFixed=denseRoots.has(b.id);
      if(aFixed&&!bFixed) {pb.x+=ux*needed;pb.y+=uy*needed/GRAPH_PANEL_Y_SCALE;}
      else if(bFixed&&!aFixed) {pa.x-=ux*needed;pa.y-=uy*needed/GRAPH_PANEL_Y_SCALE;}
      else {pa.x-=ux*needed*.5;pa.y-=uy*needed*.5/GRAPH_PANEL_Y_SCALE;
        pb.x+=ux*needed*.5;pb.y+=uy*needed*.5/GRAPH_PANEL_Y_SCALE;}
    }
    for(const node of terms) {
      const point=positions.get(node.id),radius=nodeCircleRadius(node);
      point.x=clamp(point.x,radius+14,1000-radius-14);point.y=clamp(point.y,radius+64,800-radius);
    }
  }
  for(const node of terms) {
    const point=positions.get(node.id);
    // Dense roots need enough camera-space breadth for an entire readable
    // child fan. Keeping one at the far -260 band compressed every valid 3-D
    // continuation into the same few pixels at the top of the viewport.
    let safeDepth=denseRoots.has(node.id)?clamp(point.depth,-200,180):point.depth,
      world=worldFromInitialProjection(point.x,point.y,safeDepth);
    if(vectorLength(world)>648) {
      // Preserve the already-separated screen anchor. Scaling the whole world
      // vector pulled edge nodes back into their neighbours; reducing only
      // depth keeps x/y identical in the initial camera while restoring the
      // near-plane safety margin.
      let unsafe=safeDepth,safe=0;
      for(let iteration=0;iteration<28;iteration++) {
        const candidate=(unsafe+safe)/2,test=worldFromInitialProjection(point.x,point.y,candidate);
        if(vectorLength(test)>648) unsafe=candidate; else safe=candidate;
      }
      safeDepth=safe;world=worldFromInitialProjection(point.x,point.y,safeDepth);
    }
    if(denseRoots.has(node.id)) {
      node.x=world.x;node.y=world.y;node.z=world.z;
    } else {
      const category=categoryByRole.get(node.role),length=vectorLength(world),direction=category?
        clampDirectionToCone(world,category,Math.PI/3-.02):unit(world);
      node.x=direction.x*length;node.y=direction.y*length;node.z=direction.z*length;
    }
  }
  // Cone clamping can move two boundary nodes back toward one another after
  // the screen-space solve. Re-project and resolve those residual base/base
  // collisions while reapplying the same semantic cone on every bounded pass.
  for(let iteration=0;iteration<80;iteration++) {
    const points=new Map(terms.map(node=>[node.id,projectNode(node,INITIAL_VIEW)]));
    let moved=false;
    for(let first=0;first<terms.length;first++) for(let second=first+1;second<terms.length;second++) {
      const a=terms[first],b=terms[second],pa=points.get(a.id),pb=points.get(b.id),{dx,dy,distance}=screenDelta(pa,pb),
        needed=nodeCircleRadius(a)+nodeCircleRadius(b)+10-distance;
      if(needed<=0) continue;
      moved=true;
      const ux=dx/distance,uy=dy/distance,aFixed=denseRoots.has(a.id),bFixed=denseRoots.has(b.id);
      if(aFixed&&!bFixed) {pb.x+=ux*needed;pb.y+=uy*needed/GRAPH_PANEL_Y_SCALE;}
      else if(bFixed&&!aFixed) {pa.x-=ux*needed;pa.y-=uy*needed/GRAPH_PANEL_Y_SCALE;}
      else if(!aFixed&&!bFixed) {
        pa.x-=ux*needed*.5;pa.y-=uy*needed*.5/GRAPH_PANEL_Y_SCALE;
        pb.x+=ux*needed*.5;pb.y+=uy*needed*.5/GRAPH_PANEL_Y_SCALE;
      }
    }
    if(!moved) break;
    for(const node of terms) {
      if(denseRoots.has(node.id)) continue;
      const point=points.get(node.id),radius=nodeCircleRadius(node);
      point.x=clamp(point.x,radius+14,1000-radius-14);point.y=clamp(point.y,radius+64,800-radius);
      const rawWorld=worldFromInitialProjection(point.x,point.y,point.depth),category=categoryByRole.get(node.role),length=vectorLength(rawWorld),
        direction=category?clampDirectionToCone(rawWorld,category,Math.PI/3-.02):unit(rawWorld);
      node.x=direction.x*length;node.y=direction.y*length;node.z=direction.z*length;
    }
  }
}

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

function arrangeOutwardWorldLayout(nodes,edges,canonicalChildrenByParent=new Map()) {
  const byId=new Map(nodes.map(node=>[node.id,node]));
  const categories=new Map(nodes.filter(node=>!node.term).map(node=>[node.role,node]));
  const visualParent=new Map();
  for(const edge of edges.filter(edge=>edge.relation)) visualParent.set(edge.target,edge.source);
  const siblingGroups=new Map();
  for(const [childId,parentId] of visualParent) {
    if(!siblingGroups.has(parentId)) siblingGroups.set(parentId,[]);
    siblingGroups.get(parentId).push(childId);
  }
  for(const children of siblingGroups.values()) children.sort();

  // Base nodes are immutable territory markers. Using every base axis, rather
  // than only currently expanded parents, keeps a branch's territory stable
  // when an unrelated branch appears or disappears.
  const baseAxesByRole=new Map();
  const baseRadiusByRole=new Map();
  for(const node of nodes.filter(node=>node.term&&!node.isDetail)) {
    if(node.expandable) {
      if(!baseAxesByRole.has(node.role)) baseAxesByRole.set(node.role,[]);
      baseAxesByRole.get(node.role).push({id:node.id,axis:unit(node)});
    }
    baseRadiusByRole.set(node.role,Math.max(baseRadiusByRole.get(node.role)||0,vectorLength(node)));
  }
  const screenAxesByRole=new Map();
  for(const node of nodes.filter(node=>node.term&&!node.isDetail&&node.expandable)) {
    const point=projectNode(node,INITIAL_VIEW),angle=Math.atan2(point.y-GRAPH_CENTER.y,point.x-GRAPH_CENTER.x);
    if(!screenAxesByRole.has(node.role)) screenAxesByRole.set(node.role,[]);
    screenAxesByRole.get(node.role).push({id:node.id,angle,childCount:node.childCount||0});
  }
  const angularDistance=(a,b)=>Math.abs(Math.atan2(Math.sin(a-b),Math.cos(a-b)));
  const screenTerritoryHalfAngle=parent=>{
    const point=projectNode(parent,INITIAL_VIEW),angle=Math.atan2(point.y-GRAPH_CENTER.y,point.x-GRAPH_CENTER.x);
    const neighbors=(screenAxesByRole.get(parent.role)||[]).filter(candidate=>candidate.id!==parent.id&&
      ((parent.childCount||0)<3||candidate.childCount>=3));
    const nearest=Math.min(...neighbors.map(candidate=>angularDistance(angle,candidate.angle)),Math.PI/2);
    return clamp(nearest/2-.06,.07,.32);
  };
  const angleBetween=(a,b)=>Math.acos(clamp(dot(unit(a),unit(b)),-1,1));
  const territoryHalfAngle=parent=>{
    const axis=unit(parent),neighbors=(baseAxesByRole.get(parent.role)||[]).filter(candidate=>candidate.id!==parent.id);
    const nearest=Math.min(...neighbors.map(candidate=>angleBetween(axis,candidate.axis)),Math.PI/2);
    return clamp(nearest/2-.001,.08,.24);
  };
  const localFanDirection=(parent,index,count,phase=0)=>{
    const axis=unit(parent),cameraRight={x:Math.cos(INITIAL_VIEW.yaw),y:0,z:Math.sin(INITIAL_VIEW.yaw)};
    const fallback=Math.abs(axis.y)<.88?unit(cross(axis,{x:0,y:1,z:0})):unit(cross(axis,{x:1,y:0,z:0}));
    const tangentA=unit(add(cameraRight,scale(axis,-dot(cameraRight,axis))),fallback),tangentB=unit(cross(axis,tangentA));
    const ring=Math.floor(index/4),slots=Math.min(4,count-ring*4),slot=index%4,half=territoryHalfAngle(parent)*.95;
    const azimuth=stableAngle(parent.id)+2*Math.PI*(slot+(ring%2)*.5)/slots+phase;
    const lateral=add(scale(tangentA,Math.cos(azimuth)),scale(tangentB,Math.sin(azimuth)));
    return unit(add(scale(axis,Math.cos(half)),scale(lateral,Math.sin(half))),axis);
  };
  const placed=new Set(nodes.filter(node=>!node.isDetail).map(node=>node.id)),placing=new Set();
  let denseOverflow=false;
  const setAt=(node,direction,radius)=>{
    const fixed=unit(direction,categories.get(node.role)||direction);
    node.x=fixed.x*radius;node.y=fixed.y*radius;node.z=fixed.z*radius;placed.add(node.id);
  };
  const placePrimary=id=>{
    if(placed.has(id)) return true;
    const node=byId.get(id),primaryId=visualParent.get(id);
    if(!node||!primaryId||placing.has(id)) return false;
    placing.add(id);
    const primary=byId.get(primaryId);
    if(primary?.isDetail) placePrimary(primaryId);
    if(!primary||!placed.has(primary.id)) {placing.delete(id);return false;}
    const siblings=siblingGroups.get(primaryId)||[id],index=Math.max(0,siblings.indexOf(id));
    const parentPoint=projectNode(primary,INITIAL_VIEW),parentScreenRadius=Math.hypot(parentPoint.x-GRAPH_CENTER.x,parentPoint.y-GRAPH_CENTER.y);
    const parentScreenAngle=Math.atan2(parentPoint.y-GRAPH_CENTER.y,parentPoint.x-GRAPH_CENTER.x),denseFan=siblings.length>=4,
      territoryHalf=screenTerritoryHalfAngle(primary),half=denseFan?.86:Math.max(territoryHalf,.26);
    const slotsPerRing=denseFan?4:2,screenRing=Math.floor(index/slotsPerRing),
      slots=Math.min(slotsPerRing,siblings.length-screenRing*slotsPerRing),slot=index%slotsPerRing;
    const targetScreenRadius=parentScreenRadius+104+screenRing*(denseFan?104:104);
    const slotFraction=slots===1?0:(slot-(slots-1)/2)/((slots-1)/2);
    const frameBias=denseFan?(Math.sin(parentScreenAngle)<0?half*.42:-half*.42):0,
      baseOffset=clamp(slotFraction*half*.72+frameBias,-half*.96,half*.96);
    // Detail coordinates must depend only on their canonical parent slot. If
    // another branch becomes visible later it must not move this child.
    const obstacles=nodes.filter(candidate=>candidate.id!==primaryId&&!candidate.isDetail);
    let bestPoint=null,bestClearance=-Infinity,bestSeparatedPenalty=Infinity;
    const consider=(candidateRadius,offset,depthSample)=>{
      if(candidateRadius<=parentScreenRadius+76) return;
      const angle=parentScreenAngle+offset;
      const screen={x:GRAPH_CENTER.x+candidateRadius*Math.cos(angle),y:GRAPH_CENTER.y+candidateRadius*Math.sin(angle)};
      const depthDelta=[-28,0,28,-12][slot%4]+[-112,-56,0,56,112][depthSample],depth=clamp(parentPoint.depth*.58+depthDelta,-240,240);
      const candidate=worldFromInitialProjection(screen.x,screen.y,depth),point=projectNode(candidate,INITIAL_VIEW);
      const branch=add(candidate,scale(primary,-1)),category=categories.get(node.role)||candidate;
      if(point.x<58||point.x>942||point.y<108||point.y>690||vectorLength(candidate)>648||
        vectorLength(branch)<=100||angleBetween(branch,primary)>=Math.PI/3-.04||
        vectorLength(candidate)<=vectorLength(primary)+1||angleBetween(candidate,category)>=Math.PI/3) return;
      const clearance=Math.min(...obstacles.map(obstacle=>{
        const projected=projectNode(obstacle,INITIAL_VIEW);
        return screenCircleDistance(point,projected)-renderedCircleRadius(node)-renderedCircleRadius(obstacle)-8;
      })),edgeIntrusion=obstacles.reduce((total,obstacle)=>{
        const projected=projectNode(obstacle,INITIAL_VIEW),hit=straightEdgeClearance(parentPoint,point,projected);
        return total+(hit.amount>.01&&hit.amount<.99?Math.max(0,renderedCircleRadius(obstacle)+2-hit.distance):0);
      },0);
      // Projection clearance is screen-space identical for the five depth
      // candidates. Quantize it and give the middle depth an explicit stable
      // preference so tiny engine-specific floating-point differences cannot
      // select a different 3D world anchor during hydration.
      const cellPenalty=Math.abs(offset-baseOffset)*180+Math.abs(candidateRadius-targetScreenRadius)*.28,
        stablePenalty=cellPenalty+Math.abs(depthSample-2)*1e-4,roundedClearance=Math.round(clearance*1e6)/1e6;
      if(roundedClearance>=0&&edgeIntrusion===0) {
        if(stablePenalty<bestSeparatedPenalty) {bestPoint=candidate;bestSeparatedPenalty=stablePenalty;bestClearance=roundedClearance;}
      } else if(!denseFan&&bestSeparatedPenalty===Infinity&&roundedClearance>bestClearance) {
        bestPoint=candidate;bestClearance=roundedClearance;
      }
    };
    if(denseFan) {
      const bias=Math.sin(parentScreenAngle)<0?.22:-.22;
      for(let angleSample=0;angleSample<=80;angleSample++) {
        const offset=bias-half+2*half*angleSample/80;
        for(let candidateRadius=parentScreenRadius+96;candidateRadius<=628;candidateRadius+=16)
          for(let depthSample=0;depthSample<5;depthSample++) consider(candidateRadius,offset,depthSample);
      }
    } else {
      // A sparse child still needs the complete outward cone. Restricting it
      // to a narrow preferred slot made its only straight connector pass
      // through a nearby base term even though open space existed nearby.
      for(let angleSample=0;angleSample<=72;angleSample++) {
        const offset=-1.0+2*angleSample/72;
        for(let candidateRadius=parentScreenRadius+96;candidateRadius<=628;candidateRadius+=18)
          for(let depthSample=0;depthSample<5;depthSample++) consider(candidateRadius,offset,depthSample);
      }
    }
    if(!bestPoint) {placing.delete(id);return false;}
    node.x=bestPoint.x;node.y=bestPoint.y;node.z=bestPoint.z;placed.add(node.id);
    placing.delete(id);return true;
  };

  const placeDenseSiblingGroup=(parentId,visibleIds)=>{
    const parent=byId.get(parentId);
    if(!parent||!placed.has(parentId)) return false;
    const canonical=[...new Set(canonicalChildrenByParent.get(parentId)||visibleIds)].sort(),
      children=canonical.map(id=>visualParent.get(id)===parentId&&byId.get(id)?byId.get(id):
        ({id,role:parent.role,isDetail:true,expandable:(canonicalChildrenByParent.get(id)||[]).length>0}));
    if(canonical.length<4||children.length<2) return false;
    const parentPoint=projectNode(parent,INITIAL_VIEW),parentRadius=Math.hypot(parentPoint.x-GRAPH_CENTER.x,parentPoint.y-GRAPH_CENTER.y),
      parentAngle=Math.atan2(parentPoint.y-GRAPH_CENTER.y,parentPoint.x-GRAPH_CENTER.x),
      half=canonical.length>=9?1.52:canonical.length>=5?1.16:Math.min(.94,screenTerritoryHalfAngle(parent)+.12),
      frameBias=Math.sin(parentAngle)<0?half*.28:-half*.28,
      immutable=nodes.filter(node=>!node.isDetail&&node.id!==parentId),
      immutablePoints=immutable.map(node=>({node,point:projectNode(node,INITIAL_VIEW)}));
    const candidateMap=new Map();
    for(const child of children) {
      const canonicalIndex=Math.max(0,canonical.indexOf(child.id)),ring=Math.floor(canonicalIndex/4),slot=canonicalIndex%4,
        slots=Math.min(4,canonical.length-ring*4),slotFraction=slots===1?0:(slot-(slots-1)/2)/((slots-1)/2),
        preferredOffset=clamp(slotFraction*half*.72+frameBias,-half*.96,half*.96),
        preferredRadius=parentRadius+104+ring*104,
        preferredDepth=[-120,-60,0,60,120][canonicalIndex%5],screenCandidates=[];
      for(let angleSample=0;angleSample<=72;angleSample++) {
        // Search the complete outward cone. Frame bias is a preference, not a
        // hard truncation: truncating one side left five-child branches with
        // no non-occluding batch even though valid placements existed.
        const offset=-half+2*half*angleSample/72,angle=parentAngle+offset;
        for(let candidateRadius=parentRadius+96;candidateRadius<=628;candidateRadius+=18) {
          const screen={x:GRAPH_CENTER.x+candidateRadius*Math.cos(angle),y:GRAPH_CENTER.y+candidateRadius*Math.sin(angle)};
          if(screen.x<48||screen.x>952||screen.y<60||screen.y>780) continue;
          if(screenCircleDistance(screen,parentPoint)<renderedCircleRadius(child)+renderedCircleRadius(parent)+8) continue;
          let chosen=null;
          for(const depth of [-240,-180,-120,-60,0,60,120,180,240]) {
            const candidate=worldFromInitialProjection(screen.x,screen.y,depth),branch=add(candidate,scale(parent,-1)),category=categories.get(child.role)||candidate;
            if(vectorLength(candidate)>648||vectorLength(branch)<=100||angleBetween(branch,parent)>=Math.PI/3-.04||
              vectorLength(candidate)<=vectorLength(parent)+1||angleBetween(candidate,category)>=Math.PI/3) continue;
            const depthCost=Math.abs(depth-preferredDepth);
            if(!chosen||depthCost<chosen.depthCost) chosen={world:candidate,depthCost};
          }
          if(!chosen) continue;
          const clearance=Math.min(...immutablePoints.map(({node,point})=>
            screenCircleDistance(screen,point)-renderedCircleRadius(child)-renderedCircleRadius(node)-8)),
            edgeIntrusion=immutablePoints.reduce((total,{node,point})=>
              total+Math.max(0,renderedCircleRadius(node)+2-straightEdgeDistance(parentPoint,screen,point)),0);
          const candidateDepth=projectNode(chosen.world,INITIAL_VIEW).depth,
            coveredCenterCount=immutablePoints.filter(({node,point})=>point.depth>candidateDepth+.5&&
            screenCircleDistance(screen,point)<renderedCircleRadius(node)+4).length;
          if(clearance<0) continue;
          if(edgeIntrusion>0) continue;
          if(coveredCenterCount>0) continue;
          const preference=Math.abs(offset-preferredOffset)*170+Math.abs(candidateRadius-preferredRadius)*.3+
            chosen.depthCost*.015-Math.min(clearance,80)*.04+Math.max(0,-clearance)*5+
            edgeIntrusion*1000+coveredCenterCount*10000;
          screenCandidates.push({world:chosen.world,x:screen.x,y:screen.y,offset,candidateRadius,preference});
        }
      }
      screenCandidates.sort((a,b)=>a.preference-b.preference||a.x-b.x||a.y-b.y||a.world.z-b.world.z);
      const diverse=[],seenBuckets=new Set();
      for(const candidate of screenCandidates) {
        const angleBucket=clamp(Math.floor((candidate.offset+half)/(2*half/12)),0,11),
          radialSpan=Math.max(1,628-(parentRadius+96)),radialBucket=clamp(Math.floor((candidate.candidateRadius-(parentRadius+96))/(radialSpan/4)),0,3),
          bucket=`${angleBucket}:${radialBucket}`;
        if(seenBuckets.has(bucket)) continue;
        seenBuckets.add(bucket);
        diverse.push(candidate);
      }
      for(const candidate of screenCandidates) {
        if(diverse.length>=96) break;
        if(diverse.includes(candidate)||diverse.some(saved=>Math.hypot(saved.x-candidate.x,saved.y-candidate.y)<18)) continue;
        diverse.push(candidate);
      }
      if(!diverse.length) {
        return false;
      }
      candidateMap.set(child.id,diverse);
    }
    const order=[...children].sort((a,b)=>candidateMap.get(a.id).length-candidateMap.get(b.id).length||
      canonical.indexOf(a.id)-canonical.indexOf(b.id)||a.id.localeCompare(b.id));
    const siblingEdgeIntrusion=(child,candidate,saved)=>
      Math.max(0,renderedCircleRadius(saved.child)+2-straightEdgeDistance(parentPoint,candidate,saved.candidate))+
      Math.max(0,renderedCircleRadius(child)+2-straightEdgeDistance(parentPoint,saved.candidate,candidate));
    const applyAssignment=assigned=>{
      for(const {child,candidate} of assigned) {
        const visible=visualParent.get(child.id)===parentId?byId.get(child.id):null;
        if(!visible) continue;
        visible.x=candidate.world.x;visible.y=candidate.world.y;visible.z=candidate.world.z;placed.add(visible.id);
      }
      return true;
    };
    // Solve a dense fan as one shape before considering local best-first
    // placements. Keeping every child on a shared outer arc gives each
    // straight parent edge its own angular lane; it also avoids the beam
    // solver filling the inner slots first and discovering too late that the
    // remaining labels have no unobstructed route.
    const placeArcTemplate=()=>{
      if(children.length>12) return false;
      const canonicalChildren=[...children].sort((a,b)=>canonical.indexOf(a.id)-canonical.indexOf(b.id)||a.id.localeCompare(b.id));
      for(const phase of [0,-.06,.06,-.12,.12]) for(const targetRadius of [610,592,574,556]) {
        const assigned=[];
        let valid=true;
        for(let index=0;index<canonicalChildren.length;index++) {
          const child=canonicalChildren[index],fraction=canonicalChildren.length===1?0:index/(canonicalChildren.length-1),
            targetOffset=-half*.9+2*half*.9*fraction+phase;
          const candidates=[...(candidateMap.get(child.id)||[])].sort((a,b)=>
            (Math.abs(a.offset-targetOffset)*520+Math.abs(a.candidateRadius-targetRadius))-
            (Math.abs(b.offset-targetOffset)*520+Math.abs(b.candidateRadius-targetRadius))||
            a.preference-b.preference||a.x-b.x||a.y-b.y);
          const candidate=candidates.find(option=>assigned.every(saved=>
            screenCircleDistance(saved.candidate,option)>=renderedCircleRadius(child)+renderedCircleRadius(saved.child)+8&&
            siblingEdgeIntrusion(child,option,saved)===0));
          if(!candidate) {valid=false;break;}
          assigned.push({child,candidate});
        }
        if(valid&&assigned.length===canonicalChildren.length) return applyAssignment(assigned);
      }
      return false;
    };
    if(placeArcTemplate()) return true;
    // A bounded beam can legitimately exhaust on a large synthetic fan. Do
    // not silently fall through to independent placement: reserve the entire
    // canonical fan with a deterministic farthest-first assignment instead.
    const placeSafeFallback=()=>{
      const assigned=[];
      for(const child of [...children].sort((a,b)=>canonical.indexOf(a.id)-canonical.indexOf(b.id)||a.id.localeCompare(b.id))) {
        const choices=candidateMap.get(child.id)||[];
        if(!choices.length) return false;
        const ranked=choices.map(candidate=>{
          const margin=assigned.length?Math.min(...assigned.map(saved=>screenCircleDistance(saved.candidate,candidate)-
            renderedCircleRadius(child)-renderedCircleRadius(saved.child))):Infinity;
          return {candidate,margin};
        }).sort((a,b)=>b.margin-a.margin||a.candidate.preference-b.candidate.preference||a.candidate.x-b.candidate.x||a.candidate.y-b.candidate.y);
        assigned.push({child,candidate:ranked[0].candidate});
      }
      for(let pass=0;pass<12;pass++) for(let index=0;index<assigned.length;index++) {
        const item=assigned[index],others=assigned.filter((_,otherIndex)=>otherIndex!==index);
        const ranked=(candidateMap.get(item.child.id)||[]).map(candidate=>{
          const margin=others.length?Math.min(...others.map(saved=>screenCircleDistance(saved.candidate,candidate)-
            renderedCircleRadius(item.child)-renderedCircleRadius(saved.child))):Infinity;
          return {candidate,margin};
        }).sort((a,b)=>b.margin-a.margin||a.candidate.preference-b.candidate.preference||a.candidate.x-b.candidate.x||a.candidate.y-b.candidate.y);
        item.candidate=ranked[0].candidate;
      }
      const safe=assigned.every((item,index)=>assigned.slice(index+1).every(other=>
        screenCircleDistance(item.candidate,other.candidate)>=
          renderedCircleRadius(item.child)+renderedCircleRadius(other.child)+8&&
        siblingEdgeIntrusion(item.child,item.candidate,other)===0));
      return safe&&applyAssignment(assigned);
    };
    const beamWidth=children.length>8?4096:children.length>6?1024:512;
    let beam=[{cost:0,assigned:[]}];
    for(const child of order) {
      const next=[];
      for(const state of beam) for(const candidate of candidateMap.get(child.id)) {
        const blocked=state.assigned.some(saved=>screenCircleDistance(saved.candidate,candidate)<
          renderedCircleRadius(child)+renderedCircleRadius(saved.child)+8);
        if(blocked) continue;
        const edgeIntrusion=state.assigned.reduce((total,saved)=>total+siblingEdgeIntrusion(child,candidate,saved),0);
        if(edgeIntrusion>0) continue;
        next.push({cost:state.cost+candidate.preference,assigned:[...state.assigned,{child,candidate}]});
      }
      if(!next.length) {
        return placeSafeFallback();
      }
      next.sort((a,b)=>a.cost-b.cost||a.assigned.map(item=>`${item.child.id}:${item.candidate.x.toFixed(2)}:${item.candidate.y.toFixed(2)}`).join('|')
        .localeCompare(b.assigned.map(item=>`${item.child.id}:${item.candidate.x.toFixed(2)}:${item.candidate.y.toFixed(2)}`).join('|')));
      beam=next.slice(0,beamWidth);
    }
    return applyAssignment(beam[0].assigned);
  };

  const lineageDepth=(id,seen=new Set())=>{
    if(placed.has(id)||seen.has(id)) return 0;
    const parentId=visualParent.get(id);
    return parentId?1+lineageDepth(parentId,new Set([...seen,id])):0;
  };
  const denseGroups=[...siblingGroups].filter(([parentId,visibleIds])=>(canonicalChildrenByParent.get(parentId)||visibleIds).length>=4)
    .sort(([a],[b])=>lineageDepth(a)-lineageDepth(b)||a.localeCompare(b));
  for(const [parentId,visibleIds] of denseGroups) {
    if(!placed.has(parentId)) placePrimary(parentId);
    const groupPlaced=placed.has(parentId)&&placeDenseSiblingGroup(parentId,visibleIds);
    if(!groupPlaced) {
      denseOverflow=true;
    }
  }

  for(let pass=0;pass<nodes.length;pass++) {
    let changed=false;
    for(const node of nodes.filter(node=>node.isDetail&&!placed.has(node.id))) if(placePrimary(node.id)) changed=true;
    if(!changed) break;
  }

  // Supporting prerequisite nodes with no displayed relation edge receive a
  // fixed category-relative slot derived only from their own id.
  for(const node of nodes.filter(node=>node.isDetail&&!placed.has(node.id)).sort((a,b)=>a.id.localeCompare(b.id))) {
    const supplementalIndex=node.layoutIndex||0;
    const category=categories.get(node.role)||{x:1,y:0,z:0},categoryPoint=projectNode(category,INITIAL_VIEW);
    const categoryAngle=Math.atan2(categoryPoint.y-GRAPH_CENTER.y,categoryPoint.x-GRAPH_CENTER.x);
    let bestPoint=null,bestScore=-Infinity;
    const obstacles=nodes.filter(candidate=>!candidate.isDetail);
    for(let sample=0;sample<216;sample++) {
      const angleSample=sample%72,radiusSample=Math.floor(sample/72),targetRadius=280+radiusSample*62+Math.floor(supplementalIndex/3)*50;
      const angle=categoryAngle-.72+1.44*((angleSample+stableAngle(node.id)/(2*Math.PI))%72)/71;
      const screen={x:GRAPH_CENTER.x+targetRadius*Math.cos(angle),y:GRAPH_CENTER.y+targetRadius*Math.sin(angle)};
      const depth=clamp(categoryPoint.depth*(targetRadius/115)+((supplementalIndex%3)-1)*45,-420,420);
      const candidate=worldFromInitialProjection(screen.x,screen.y,depth),point=projectNode(candidate,INITIAL_VIEW);
      const clearance=Math.min(...obstacles.map(obstacle=>{const projected=projectNode(obstacle,INITIAL_VIEW);return Math.hypot(point.x-projected.x,point.y-projected.y);}));
      const framePenalty=Math.max(0,48-point.x,point.x-952,92-point.y,point.y-748)*6,score=clearance-framePenalty;
      if(score>bestScore) {bestPoint=candidate;bestScore=score;}
    }
    if(bestPoint) {node.x=bestPoint.x;node.y=bestPoint.y;node.z=bestPoint.z;placed.add(node.id);}
  }
  if(straightLayoutIsUnsafe(nodes,edges)) {
    denseOverflow=true;
  }
  return {denseOverflow};
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

function buildExpandedTermGraphVisible(baseTerms, catalogTerms, expandedIds=[]) {
  const {termsById,childrenByParent}=relationshipIndex(catalogTerms);
  const childCounts=new Map([...childrenByParent].map(([id,children])=>[id,children.length]));
  const base=buildTermGraph(baseTerms,childCounts);
  const baseIds=new Set(baseTerms.map(term=>term.term_id));
  const expandedOrder=[...new Set(expandedIds)],expanded=new Set(expandedOrder);
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
        // Expanding a parent reveals that parent's direct children only. A
        // child's other prerequisites remain semantic metadata; exposing them
        // here made unrelated peer/parent nodes appear as if they were newly
        // discovered children.
        if(termsById.has(childId)&&!visible.has(childId)) {visible.add(childId);changed=true;}
      }
    }
  }

  const nodes=base.nodes.map(node=>node.term ? {...node,expandable:(childrenByParent.get(node.id)||[]).length>0} : node);
  const nodeById=new Map(nodes.map(node=>[node.id,node]));
  const categoryByRole=new Map(nodes.filter(node=>!node.term).map(node=>[node.role,node]));
  const roleCounts=new Map(),catalogIndexById=new Map();
  for(const term of catalogTerms) {
    const index=roleCounts.get(term.role)||0;catalogIndexById.set(term.term_id,index);roleCounts.set(term.role,index+1);
  }
  const makeNode=(term,anchor,angle,distance)=>({id:term.term_id,label:term.label_ko,role:term.role,term,isDetail:true,
    expandable:(childrenByParent.get(term.term_id)||[]).length>0,
    layoutIndex:catalogIndexById.get(term.term_id)||0,
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
        const key=`${parentId}:${childId}:${relation}`;
        if(!relationshipKeys.has(key)) {relationships.push({source:parentId,target:childId,relation});relationshipKeys.add(key);}
      }
    }
  }
  const edges=[...base.edges];
  for(const node of nodes.filter(node=>node.isDetail)) {
    const candidates=relationships.filter(edge=>edge.target===node.id&&nodeById.has(edge.source));
    const preferred=revealOrigin.get(node.id);
    const representative=candidates.find(edge=>edge.source===preferred)||candidates[0];
    if(representative) edges.push(representative);
    else {
      const category=categoryByRole.get(node.role);
      if(category) edges.push({source:category.id,target:node.id});
    }
  }
  let denseOverflow=false;
  if(expanded.size>0) {
    denseOverflow=arrangeOutwardWorldLayout(nodes,edges,childrenByParent).denseOverflow;
    for(const node of nodes.filter(node=>node.isDetail&&vectorLength(node)>648)) {
      const direction=unit(node);node.x=direction.x*648;node.y=direction.y*648;node.z=direction.z*648;
    }
    if(straightLayoutIsUnsafe(nodes,edges)) denseOverflow=true;
  }
  return {nodes,edges,relationships,denseOverflow};
}

function stabilizeCatalogLayout(graph,childrenByParent) {
  const nodes=graph.nodes.map(node=>({...node})),byId=new Map(nodes.map(node=>[node.id,node])),
    points=new Map(nodes.map(node=>[node.id,{...projectNode(node,INITIAL_VIEW)}])),anchors=new Map(),
    relationEdges=graph.edges.filter(edge=>edge.relation&&byId.has(edge.source)&&byId.has(edge.target)),
    potentialEdges=[...childrenByParent].flatMap(([source,targets])=>targets
      .filter(target=>byId.has(source)&&byId.has(target)).map(target=>({source,target,relation:'catalog'}))),
    relationTargetsBySource=new Map(),
    denseEntry=[...childrenByParent].filter(([parentId,children])=>byId.has(parentId)&&children.filter(id=>byId.has(id)).length>=9)
      .sort(([,a],[,b])=>b.length-a.length)[0],fixed=new Set();
  if(nodes.length===ACTIVE_CATALOG_LAYOUT.size&&nodes.every(node=>ACTIVE_CATALOG_LAYOUT.has(node.id))) {
    for(const node of nodes) {
      const world=ACTIVE_CATALOG_LAYOUT.get(node.id);
      node.x=world.x;node.y=world.y;node.z=world.z;
    }
    const result={...graph,nodes};
    // The approved layout is safe in world space. A projected overlap at one
    // camera angle is normal 3-D occlusion and must not replace + expansion
    // with the list view.
    result.denseOverflow=false;
    return result;
  }
  for(const edge of relationEdges) {
    if(!relationTargetsBySource.has(edge.source)) relationTargetsBySource.set(edge.source,[]);
    relationTargetsBySource.get(edge.source).push(edge.target);
  }
  if(denseEntry) {
    const [parentId,allChildren]=denseEntry,children=allChildren.filter(id=>byId.has(id)).sort(),parent=byId.get(parentId),
      category=byId.get(`category:${parent.role}`),parentPoint={x:440,y:420,depth:-40},panelCenterY=420*GRAPH_PANEL_Y_SCALE;
    if(category) {points.set(category.id,{x:340,y:420,depth:80});fixed.add(category.id);}
    points.set(parentId,parentPoint);fixed.add(parentId);
    children.forEach((id,index)=>{
      const innerCount=Math.min(4,children.length),outerCount=Math.max(0,children.length-innerCount),inner=index<innerCount,
        slot=inner?index:index-innerCount,count=inner?innerCount:outerCount,
        angle=inner?-.81+1.62*(count===1?.5:slot/(count-1)):-1.42+2.84*(count===1?.5:slot/(count-1)),
        fanRadius=inner?190:300,point={x:GRAPH_CENTER.x+fanRadius*Math.cos(angle),
          y:(panelCenterY+fanRadius*Math.sin(angle))/GRAPH_PANEL_Y_SCALE,
          depth:-150+300*(children.length===1?.5:index/(children.length-1))};
      points.set(id,point);anchors.set(id,{...point});
    });
  }
  // Shared detail terms must stay usable from either of their possible parents.
  // Reserve those small parent components before the global relaxation so the
  // remaining nodes yield to both straight corridors instead of moving when a
  // different parent is expanded later.
  const reservedComponents=new Map([
    ['pose_contrapposto',{x:740,y:308.824,depth:120}],
    ['pose_weight_shift',{x:840,y:333.529,depth:60}],
    ['pose_contrapposto_weight_shift',{x:920,y:160.588,depth:180}],
  ]);
  for(const [id,point] of reservedComponents) if(byId.has(id)) {
    points.set(id,{...point});
    fixed.add(id);
  }
  const radius=node=>renderedCircleRadius(node);
  const move=(node,dx,dy,amount=1)=>{
    if(fixed.has(node.id)) return false;
    const point=points.get(node.id);point.x+=dx*amount;point.y+=dy*amount/GRAPH_PANEL_Y_SCALE;return true;
  };
  for(let iteration=0;iteration<900;iteration++) {
    let changed=false;
    for(let first=0;first<nodes.length;first++) for(let second=first+1;second<nodes.length;second++) {
      const a=nodes[first],b=nodes[second],pa=points.get(a.id),pb=points.get(b.id),{dx,dy,distance}=screenDelta(pa,pb),
        needed=radius(a)+radius(b)+2-distance;
      if(needed<=0) continue;
      const ux=dx/distance,uy=dy/distance,aFixed=fixed.has(a.id),bFixed=fixed.has(b.id);
      if(aFixed&&!bFixed) changed=move(b,ux,uy,needed)||changed;
      else if(bFixed&&!aFixed) changed=move(a,-ux,-uy,needed)||changed;
      else if(!aFixed&&!bFixed) {
        changed=move(a,-ux,-uy,needed*.5)||changed;changed=move(b,ux,uy,needed*.5)||changed;
      }
    }
    for(const [sourceId,targetIds] of relationTargetsBySource) {
      const source=points.get(sourceId),sx=source.x,sy=source.y*GRAPH_PANEL_Y_SCALE;
      for(let first=0;first<targetIds.length;first++) for(let second=first+1;second<targetIds.length;second++) {
        const a=byId.get(targetIds[first]),b=byId.get(targetIds[second]),pa=points.get(a.id),pb=points.get(b.id),
          hitA=straightEdgeClearance(source,pa,pb),hitB=straightEdgeClearance(source,pb,pa),
          needed=Math.max(radius(b)+6-hitA.distance,radius(a)+6-hitB.distance);
        if(needed<=0) continue;
        const ax=pa.x-sx,ay=pa.y*GRAPH_PANEL_Y_SCALE-sy,bx=pb.x-sx,by=pb.y*GRAPH_PANEL_Y_SCALE-sy,
          crossSign=ax*by-ay*bx>=0?1:-1,alen=Math.hypot(ax,ay)||1,blen=Math.hypot(bx,by)||1;
        changed=move(a,ay/alen*crossSign,-ax/alen*crossSign,needed*.55)||changed;
        changed=move(b,-by/blen*crossSign,bx/blen*crossSign,needed*.55)||changed;
      }
    }
    for(const edge of potentialEdges) {
      const source=points.get(edge.source),target=points.get(edge.target);
      for(const obstacle of nodes) {
        if(obstacle.id===edge.source||obstacle.id===edge.target||fixed.has(obstacle.id)) continue;
        const point=points.get(obstacle.id),hit=straightEdgeClearance(source,target,point),needed=radius(obstacle)+4-hit.distance;
        if(hit.amount<=.04||hit.amount>=.96||needed<=0) continue;
        const sx=source.x,sy=source.y*GRAPH_PANEL_Y_SCALE,tx=target.x,ty=target.y*GRAPH_PANEL_Y_SCALE,
          ex=tx-sx,ey=ty-sy,length=Math.hypot(ex,ey)||1,nx=-ey/length,ny=ex/length,
          side=(point.x-(sx+ex*hit.amount))*nx+(point.y*GRAPH_PANEL_Y_SCALE-(sy+ey*hit.amount))*ny;
        changed=move(obstacle,nx*(side>=0?1:-1),ny*(side>=0?1:-1),needed)||changed;
      }
    }
    for(const node of nodes) {
      if(fixed.has(node.id)) continue;
      const point=points.get(node.id),r=radius(node),beforeX=point.x,beforeY=point.y;
      point.x=clamp(point.x,r+10,990-r);point.y=clamp(point.y,(r+18)/GRAPH_PANEL_Y_SCALE,(662-r)/GRAPH_PANEL_Y_SCALE);
      if(point.x!==beforeX||point.y!==beforeY) changed=true;
    }
    for(const [sourceId,targetIds] of relationTargetsBySource) {
      const source=points.get(sourceId),sx=source.x,sy=source.y*GRAPH_PANEL_Y_SCALE;
      for(let first=0;first<targetIds.length;first++) for(let second=first+1;second<targetIds.length;second++) {
        const a=byId.get(targetIds[first]),b=byId.get(targetIds[second]),pa=points.get(a.id),pb=points.get(b.id),
          hitA=straightEdgeClearance(source,pa,pb),hitB=straightEdgeClearance(source,pb,pa);
        if((hitA.amount<=.04||hitA.amount>=.96||hitA.distance>=radius(b)+8)&&
          (hitB.amount<=.04||hitB.amount>=.96||hitB.distance>=radius(a)+8)) continue;
        const ax=pa.x-sx,ay=pa.y*GRAPH_PANEL_Y_SCALE-sy,bx=pb.x-sx,by=pb.y*GRAPH_PANEL_Y_SCALE-sy,
          crossSign=ax*by-ay*bx>=0?1:-1,alen=Math.hypot(ax,ay)||1,blen=Math.hypot(bx,by)||1,
          needed=Math.max(radius(b)+8-hitA.distance,radius(a)+8-hitB.distance,2);
        changed=move(a,ay/alen*crossSign,-ax/alen*crossSign,needed*.8)||changed;
        changed=move(b,-by/blen*crossSign,bx/blen*crossSign,needed*.8)||changed;
      }
    }
    if(!changed) break;
  }
  // A movable node can otherwise oscillate between two reserved component
  // anchors. Resolve those rare wedges with one deterministic nearest-slot
  // search after relaxation; this is still part of the one-time catalog
  // layout and never runs in response to an expand/collapse interaction.
  for(let repairPass=0;repairPass<3;repairPass++) for(const node of nodes.filter(candidate=>!fixed.has(candidate.id))) {
    const current=points.get(node.id),isClear=candidate=>{
      if(candidate.x<radius(node)+10||candidate.x>990-radius(node)||
        candidate.y*GRAPH_PANEL_Y_SCALE<radius(node)+18||candidate.y*GRAPH_PANEL_Y_SCALE>662-radius(node)) return false;
      if(vectorLength(worldFromInitialProjection(candidate.x,candidate.y,candidate.depth))>648) return false;
      for(const obstacle of nodes) if(obstacle.id!==node.id&&
        screenCircleDistance(candidate,points.get(obstacle.id))<radius(node)+radius(obstacle)+2) return false;
      for(const edge of potentialEdges) if(edge.source!==node.id&&edge.target!==node.id) {
        const hit=straightEdgeClearance(points.get(edge.source),points.get(edge.target),candidate);
        if(hit.amount>.04&&hit.amount<.96&&hit.distance<radius(node)+2) return false;
      }
      return true;
    };
    if(isClear(current)) continue;
    const choices=[];
    for(let x=radius(node)+10;x<=990-radius(node);x+=8)
      for(let panelY=radius(node)+18;panelY<=662-radius(node);panelY+=8) {
        const candidate={x,y:panelY/GRAPH_PANEL_Y_SCALE,depth:current.depth};
        if(isClear(candidate)) choices.push({candidate,score:screenCircleDistance(current,candidate)});
      }
    choices.sort((a,b)=>a.score-b.score||a.candidate.x-b.candidate.x||a.candidate.y-b.candidate.y);
    if(choices.length) points.set(node.id,choices[0].candidate);
  }
  const candidateIsSafe=(child,source,candidate)=>{
    if(candidate.x<radius(child)+10||candidate.x>990-radius(child)||
      candidate.y*GRAPH_PANEL_Y_SCALE<radius(child)+18||candidate.y*GRAPH_PANEL_Y_SCALE>662-radius(child)) return false;
    const incoming=potentialEdges.filter(edge=>edge.target===child.id);
    for(const edge of incoming) {
      const sourcePoint=points.get(edge.source),outwardX=sourcePoint.x-GRAPH_CENTER.x,
        outwardY=(sourcePoint.y-GRAPH_CENTER.y)*GRAPH_PANEL_Y_SCALE,branchX=candidate.x-sourcePoint.x,
        branchY=(candidate.y-sourcePoint.y)*GRAPH_PANEL_Y_SCALE;
      if(outwardX*branchX+outwardY*branchY<=0) return false;
    }
    for(const obstacle of nodes) {
      if(obstacle.id===child.id) continue;
      const point=points.get(obstacle.id);
      if(screenCircleDistance(candidate,point)<radius(child)+radius(obstacle)+1) return false;
      for(const edge of incoming) if(obstacle.id!==edge.source) {
        const hit=straightEdgeClearance(points.get(edge.source),candidate,point);
        if(hit.amount>.04&&hit.amount<.96&&hit.distance<radius(obstacle)+2) return false;
      }
    }
    for(const edge of potentialEdges) {
      if(edge.target===child.id||edge.source===child.id) continue;
      const hit=straightEdgeClearance(points.get(edge.source),points.get(edge.target),candidate);
      if(hit.amount>.04&&hit.amount<.96&&hit.distance<radius(child)+2) return false;
    }
    return true;
  };
  for(let pass=0;pass<3;pass++) for(const edge of potentialEdges) {
    const child=byId.get(edge.target),source=byId.get(edge.source),current=points.get(child.id);
    if(fixed.has(child.id)) continue;
    if(candidateIsSafe(child,source,current)) continue;
    const sourcePoint=points.get(source.id),axis=Math.atan2((sourcePoint.y-GRAPH_CENTER.y)*GRAPH_PANEL_Y_SCALE,
      sourcePoint.x-GRAPH_CENTER.x),choices=[];
    for(let angleIndex=0;angleIndex<=72;angleIndex++) {
      const angle=axis-1.42+2.84*angleIndex/72;
      for(let distance=110;distance<=430;distance+=16) {
        const candidate={x:sourcePoint.x+Math.cos(angle)*distance,
          y:(sourcePoint.y*GRAPH_PANEL_Y_SCALE+Math.sin(angle)*distance)/GRAPH_PANEL_Y_SCALE,depth:current.depth};
        if(candidateIsSafe(child,source,candidate)) choices.push({candidate,score:screenCircleDistance(current,candidate)});
      }
    }
    if(!choices.length) for(let x=radius(child)+10;x<=990-radius(child);x+=8)
      for(let panelY=radius(child)+18;panelY<=662-radius(child);panelY+=8) {
        const candidate={x,y:panelY/GRAPH_PANEL_Y_SCALE,depth:current.depth};
        if(candidateIsSafe(child,source,candidate)) choices.push({candidate,score:screenCircleDistance(current,candidate)});
      }
    choices.sort((a,b)=>a.score-b.score||a.candidate.x-b.candidate.x||a.candidate.y-b.candidate.y);
    if(choices.length) points.set(child.id,choices[0].candidate);
  }
  for(let pass=0;pass<potentialEdges.length;pass++) {
    let repaired=false;
    for(const edge of potentialEdges) {
      const sourcePoint=points.get(edge.source),targetPoint=points.get(edge.target);
      for(const obstacle of nodes) {
        if(obstacle.id===edge.source||obstacle.id===edge.target) continue;
        const incoming=potentialEdges.find(candidate=>candidate.target===obstacle.id);
        if(!incoming||fixed.has(obstacle.id)) continue;
        const hit=straightEdgeClearance(sourcePoint,targetPoint,points.get(obstacle.id));
        if(hit.amount<=.04||hit.amount>=.96||hit.distance>=radius(obstacle)+2) continue;
        const obstacleSource=byId.get(incoming.source),current=points.get(obstacle.id),parentPoint=points.get(obstacleSource.id),
          axis=Math.atan2((parentPoint.y-GRAPH_CENTER.y)*GRAPH_PANEL_Y_SCALE,parentPoint.x-GRAPH_CENTER.x),choices=[];
        for(let angleIndex=0;angleIndex<=120;angleIndex++) {
          const angle=axis-1.56+3.12*angleIndex/120;
          for(let distance=110;distance<=460;distance+=10) {
            const candidate={x:parentPoint.x+Math.cos(angle)*distance,
              y:(parentPoint.y*GRAPH_PANEL_Y_SCALE+Math.sin(angle)*distance)/GRAPH_PANEL_Y_SCALE,depth:current.depth};
            if(candidateIsSafe(obstacle,obstacleSource,candidate))
              choices.push({candidate,score:screenCircleDistance(current,candidate)});
          }
        }
        if(!choices.length) for(let x=radius(obstacle)+10;x<=990-radius(obstacle);x+=8)
          for(let panelY=radius(obstacle)+18;panelY<=662-radius(obstacle);panelY+=8) {
            const candidate={x,y:panelY/GRAPH_PANEL_Y_SCALE,depth:current.depth};
            if(candidateIsSafe(obstacle,obstacleSource,candidate))
              choices.push({candidate,score:screenCircleDistance(current,candidate)});
          }
        choices.sort((a,b)=>a.score-b.score||a.candidate.x-b.candidate.x||a.candidate.y-b.candidate.y);
        if(choices.length) {points.set(obstacle.id,choices[0].candidate);repaired=true;break;}
      }
      if(repaired) break;
    }
    if(!repaired) break;
  }
  for(const node of nodes) {
    const point=points.get(node.id),depth=clamp(point.depth??0,-180,180),world=worldFromInitialProjection(point.x,point.y,depth);
    node.x=world.x;node.y=world.y;node.z=world.z;
  }
  const result={...graph,nodes};
  result.denseOverflow=straightLayoutIsUnsafe(nodes,graph.edges);
  return result;
}

export function buildExpandedTermGraph(baseTerms,catalogTerms,expandedIds=[]) {
  const {childrenByParent}=relationshipIndex(catalogTerms),baseIds=new Set(baseTerms.map(term=>term.term_id)),
    expandable=[...childrenByParent].filter(([id])=>baseIds.has(id)).map(([id])=>id).sort(),
    largest=Math.max(0,...expandable.map(id=>(childrenByParent.get(id)||[]).length));
  if(largest<9||largest>12) return buildExpandedTermGraphVisible(baseTerms,catalogTerms,expandedIds);
  let baseCache=stabilizedLayoutCache.get(catalogTerms);
  if(!baseCache) {baseCache=new WeakMap();stabilizedLayoutCache.set(catalogTerms,baseCache);}
  let universe=baseCache.get(baseTerms);
  if(!universe) {
    universe=stabilizeCatalogLayout(buildExpandedTermGraphVisible(baseTerms,catalogTerms,expandable),childrenByParent);
    baseCache.set(baseTerms,universe);
  }
  const
    requested=buildExpandedTermGraphVisible(baseTerms,catalogTerms,expandedIds),universeById=new Map(universe.nodes.map(node=>[node.id,node]));
  for(const node of requested.nodes) {
    const stable=universeById.get(node.id);
    if(stable) {node.x=stable.x;node.y=stable.y;node.z=stable.z;}
  }
  requested.denseOverflow=universe.nodes.length===ACTIVE_CATALOG_LAYOUT.size&&
    universe.nodes.every(node=>ACTIVE_CATALOG_LAYOUT.has(node.id))?false:straightLayoutIsUnsafe(requested.nodes,requested.edges);
  return requested;
}

export function projectNode(node, view) {
  const x = node.x*Math.cos(view.yaw)+node.z*Math.sin(view.yaw);
  const z = -node.x*Math.sin(view.yaw)+node.z*Math.cos(view.yaw);
  const y = node.y*Math.cos(view.pitch)-z*Math.sin(view.pitch);
  const depth = node.y*Math.sin(view.pitch)+z*Math.cos(view.pitch);
  const perspective = 1100/(1100-depth);
  const zoom=clamp(view.zoom,.65,1.6);
  return {x:500+x*perspective*zoom,y:480+y*perspective*zoom,depth,scale:clamp(perspective,.65,1.6),
    opacity:clamp(.84+depth/1800,.72,1)};
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
