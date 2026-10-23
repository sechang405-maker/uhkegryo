import { approvedCatalogWorldLayout } from "./term-graph-approved-layout.mjs";
import { INITIAL_VIEW } from "./term-graph.mjs";

const RESERVED_LAYOUT = approvedCatalogWorldLayout(INITIAL_VIEW);
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
const ROLE_PHASE = Object.freeze({ body: .35, pose: 1.7, composition: 3.15, perspective: 4.55 });
const NODE_CLEARANCE = 88;
const EDGE_CLEARANCE = 44;

const length = (vector) => Math.hypot(vector.x, vector.y, vector.z);
const unit = (vector, fallback = { x: 1, y: 0, z: 0 }) => {
  const amount = length(vector);
  return amount > 1e-8 ? { x: vector.x / amount, y: vector.y / amount, z: vector.z / amount } : fallback;
};
const cross = (a, b) => ({ x: a.y*b.z-a.z*b.y, y: a.z*b.x-a.x*b.z, z: a.x*b.y-a.y*b.x });
const add = (...vectors) => vectors.reduce((sum, vector) => ({
  x: sum.x + vector.x, y: sum.y + vector.y, z: sum.z + vector.z,
}), { x: 0, y: 0, z: 0 });
const scale = (vector, amount) => ({ x: vector.x*amount, y: vector.y*amount, z: vector.z*amount });
const distance = (a, b) => Math.hypot(a.x-b.x, a.y-b.y, a.z-b.z);

function segmentDistance(start, end, point) {
  const dx=end.x-start.x,dy=end.y-start.y,dz=end.z-start.z,
    squared=dx*dx+dy*dy+dz*dz,
    amount=squared?Math.max(0,Math.min(1,((point.x-start.x)*dx+(point.y-start.y)*dy+(point.z-start.z)*dz)/squared)):0;
  return Math.hypot(point.x-start.x-dx*amount,point.y-start.y-dy*amount,point.z-start.z-dz*amount);
}

function stableNumber(value) {
  let hash=2166136261;
  for(const character of String(value)) hash=Math.imul(hash^character.codePointAt(0),16777619)>>>0;
  return hash;
}

function candidateFor(role, slot, termId, attempt) {
  const hub=RESERVED_LAYOUT.get(`category:${role}`);
  if(!hub) return null;
  const outward=unit(hub),reference=Math.abs(outward.y)<.82?{x:0,y:1,z:0}:{x:1,y:0,z:0},
    tangent=unit(cross(outward,reference)),bitangent=unit(cross(outward,tangent)),
    shell=Math.floor(slot/4),lane=slot%4,
    seeded=(stableNumber(termId)%997)/997,
    angle=(ROLE_PHASE[role]||0)+lane*Math.PI/2+shell*GOLDEN_ANGLE+seeded*.34+attempt*GOLDEN_ANGLE,
    // Each persisted slot owns its own radial band. Candidate retries only
    // rotate inside that band, so adding or deleting another personal term
    // can never move an already saved node.
    outwardDistance=176+slot*132,
    spread=(130+slot*72)*(.58+(attempt%6)*.14);
  return add(hub,scale(outward,outwardDistance),scale(tangent,Math.cos(angle)*spread),
    scale(bitangent,Math.sin(angle)*spread));
}

function safeAgainstApproved(role, candidate, earlierSlots = []) {
  const hub=RESERVED_LAYOUT.get(`category:${role}`);
  for(const [id, obstacle] of RESERVED_LAYOUT) {
    if(id===`category:${role}`) continue;
    if(distance(candidate,obstacle)<NODE_CLEARANCE) return false;
    const hit=segmentDistance(hub,candidate,obstacle);
    if(hit<EDGE_CLEARANCE) return false;
  }
  for(const obstacle of earlierSlots) {
    if(distance(candidate,obstacle)<NODE_CLEARANCE) return false;
    if(segmentDistance(hub,candidate,obstacle)<EDGE_CLEARANCE) return false;
    if(segmentDistance(hub,obstacle,candidate)<EDGE_CLEARANCE) return false;
  }
  return true;
}

const slotCache=new Map();
function personalPoint(term) {
  const slot=Number.isInteger(term.layout_slot)&&term.layout_slot>=0?term.layout_slot:stableNumber(term.term_id)%1024,
    key=term.role,points=slotCache.get(key)||[];
  for(let current=points.length;current<=slot;current++) {
    let chosen=null;
    for(let attempt=0;attempt<96;attempt++) {
      const candidate=candidateFor(term.role,current,`${term.role}:${current}`,attempt);
      if(candidate&&safeAgainstApproved(term.role,candidate,points)) {chosen=candidate;break;}
    }
    points.push(chosen||candidateFor(term.role,current,`${term.role}:${current}`,96));
  }
  slotCache.set(key,points);
  return points[slot];
}

export function personalGraphTerms(records = []) {
  return records.filter(record=>record?.status==="active"&&record.term_id&&record.role&&Number.isInteger(record.layout_slot))
    .map(record=>{
      const query=(record.query_fragments_en||[]).filter(Boolean).join(" ").trim();
      return {
      role:record.role,term_id:record.term_id,label_ko:record.label_ko,
      plain_meaning_ko:record.plain_meaning_ko,reference_checkpoints:[...(record.reference_checkpoints_ko||[])],
      cautions:[...(record.cautions_ko||[])],query_fragments:[...(record.query_fragments_en||[])],
      recommended_search_query:query?`${query} drawing`:null,requires_all_of:[],requires_any_of:[],
      search_disabled:!query,is_personal:true,layout_slot:record.layout_slot,
    };});
}

export function attachPersonalTermOverlay(graph, records = []) {
  const publicIds=new Set(graph.nodes.map(node=>node.id)),nodes=[...graph.nodes],edges=[...graph.edges];
  const terms=personalGraphTerms(records).filter(term=>!publicIds.has(term.term_id))
    .sort((a,b)=>a.role.localeCompare(b.role)||a.layout_slot-b.layout_slot||a.term_id.localeCompare(b.term_id));
  for(const term of terms) {
    const point=personalPoint(term);
    if(!point||!publicIds.has(`category:${term.role}`)) continue;
    nodes.push({id:term.term_id,label:term.label_ko,role:term.role,term,childCount:0,isPersonal:true,
      x:point.x,y:point.y,z:point.z});
    edges.push({source:`category:${term.role}`,target:term.term_id,personal:true});
  }
  return {...graph,nodes,edges,personalTerms:terms};
}
