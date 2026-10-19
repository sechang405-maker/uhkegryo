import { createMindMapSlots } from './term-mind-map.mjs';

export const INITIAL_VIEW = Object.freeze({ yaw: 0, pitch: 0, zoom: 1 });
export const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

export function buildTermGraph(terms) {
  const seen = new Set();
  const slots = createMindMapSlots(terms);
  const centers = [[-230,-155,60],[220,-130,-80],[260,150,65],[-230,175,-65],[0,25,-100]];
  const nodes = [], edges = [];
  slots.forEach((slot, index) => {
    const [x,y,z] = centers[index];
    const id = `category:${slot.role}`;
    nodes.push({id, label:slot.roleLabel, role:slot.role, x,y,z});
    slot.terms.forEach((term,i) => {
      if(seen.has(term.term_id)) return;
      seen.add(term.term_id);
      const angle = (-150 + i * 115) * Math.PI / 180;
      nodes.push({id:term.term_id,label:term.label_ko,role:slot.role,term,
        x:x+115*Math.cos(angle),y:y+95*Math.sin(angle),z:z+(i-1)*90});
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

export function appendTerms(draft, terms) {
  let next=draft;
  for(const term of terms) {
    if(!next.includes(term.label_ko)) next += `${next && !/\s$/.test(next) ? ', ' : ''}${term.label_ko}`;
  }
  return [...next].length<=500 ? next : null;
}
