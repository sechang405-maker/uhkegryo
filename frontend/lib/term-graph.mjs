import { createMindMapSlots } from './term-mind-map.mjs';

export const INITIAL_VIEW = Object.freeze({ yaw: 0, pitch: 0, zoom: 1 });
export const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

export function buildTermGraph(terms) {
  const seen = new Set();
  const slots = createMindMapSlots(terms);
  const centers = [[-235,-160,0],[235,-160,-25],[235,165,0],[-235,165,-25]];
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
        x:x+145*radius*Math.cos(angle),y:y+125*latitude,z:z+100*radius*Math.sin(angle)});
      edges.push({source:id,target:term.term_id});
    });
  });
  return {nodes,edges};
}

export function projectNode(node, view) {
  const x = node.x*Math.cos(view.yaw)+node.z*Math.sin(view.yaw);
  const z = -node.x*Math.sin(view.yaw)+node.z*Math.cos(view.yaw);
  const y = node.y*Math.cos(view.pitch)-z*Math.sin(view.pitch);
  const depth = node.y*Math.sin(view.pitch)+z*Math.cos(view.pitch);
  const perspective = 1000/(1000-depth);
  const zoom=clamp(view.zoom,.65,1.6);
  return {x:500+x*perspective*zoom,y:350+y*perspective*zoom,depth,scale:clamp(perspective,.8,1.2)};
}

export function toggleTerm(ids, id) {
  return ids.includes(id) ? ids.filter(value=>value!==id) : [...ids,id];
}

// Keep the larger reviewed catalog readable after projecting its 3D positions.
export function separateGraphLabels(graph, view, width = 1000, height = 600, compact = false) {
  const points = graph.nodes.map(node => {
    const projected = projectNode(node, view);
    return {...projected, id:node.id, x:projected.x*width/1000, y:projected.y*height/700,
      w:node.term ? compact ? 42 : 158 : 50, h:node.term ? compact ? 42 : 56 : 50};
  });
  const constrain = p => {
    p.x=clamp(p.x,p.w/2+4,width-p.w/2-4);
    p.y=clamp(p.y,p.h/2+4,height-p.h/2-4);
  };
  points.forEach(constrain);
  for(let pass=0;pass<100;pass++) {
    let overlaps=0;
    for(let i=0;i<points.length;i++) for(let j=0;j<i;j++) {
      const a=points[i],b=points[j],dx=a.x-b.x,dy=a.y-b.y;
      const overlapX=(a.w+b.w)/2+6-Math.abs(dx),overlapY=(a.h+b.h)/2+6-Math.abs(dy);
      if(overlapX<=0 || overlapY<=0) continue;
      overlaps++;
      if(overlapX<overlapY) {const push=(overlapX+.1)/2*(dx>=0?1:-1);a.x+=push;b.x-=push;}
      else {const push=(overlapY+.1)/2*(dy>=0?1:-1);a.y+=push;b.y-=push;}
      constrain(a);constrain(b);
    }
    if(!overlaps) break;
  }
  const collides = points.some((a,i)=>points.slice(0,i).some(b=>
    Math.abs(a.x-b.x)<(a.w+b.w)/2+2 && Math.abs(a.y-b.y)<(a.h+b.h)/2+2));
  if(collides) {
    // Dense projections use distinct nearby slots rather than hiding any card.
    const columns=Math.max(1,Math.floor(width/(Math.max(...points.map(p=>p.w))+6)));
    const rows=Math.ceil(points.length/columns);
    const cells=Array.from({length:columns*rows},(_,i)=>({x:(i%columns+.5)*width/columns,y:(Math.floor(i/columns)+.5)*height/rows}));
    for(const p of points) {
      let closest=0;
      for(let i=1;i<cells.length;i++) if(Math.hypot(cells[i].x-p.x,cells[i].y-p.y)<Math.hypot(cells[closest].x-p.x,cells[closest].y-p.y)) closest=i;
      Object.assign(p,cells.splice(closest,1)[0]);
    }
  }
  return Object.fromEntries(points.map(p=>[p.id,{...p,x:p.x*1000/width,y:p.y*700/height}]));
}

export function appendTerms(draft, terms) {
  let next=draft;
  for(const term of terms) {
    if(!next.includes(term.label_ko)) next += `${next && !/\s$/.test(next) ? ', ' : ''}${term.label_ko}`;
  }
  return [...next].length<=500 ? next : null;
}
