import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { ACTIVE_TERMS, HOME_TERMS } from "../lib/home-catalog.mjs";
import { buildExpandedTermGraph } from "../lib/term-graph.mjs";
import { attachPersonalTermOverlay, personalGraphTerms } from "../lib/term-graph-personal-layout.mjs";
import { createGraphSearchScope } from "../lib/recommended-query.mjs";

const personal = (overrides = {}) => ({
  term_id: "personal_11111111111111111111111111111111",
  status: "active", role: "pose", layout_slot: 0,
  label_ko: "발레 아라베스크", label_en: "Ballet arabesque",
  plain_meaning_ko: "한쪽 다리로 서서 반대쪽 다리를 뒤로 길게 뻗는 발레 자세입니다.",
  reference_checkpoints_ko: ["축이 되는 다리의 균형"], cautions_ko: [],
  aliases_ko: ["아라베스크"], query_fragments_en: ["ballet arabesque pose"],
  proposal_kind: "descriptive", uncertainty_ko: null,
  ...overrides,
});

const coordinates = (graph) => Object.fromEntries(graph.nodes.map(({id,x,y,z}) => [id,{x,y,z}]));
const distance = (a,b) => Math.hypot(a.x-b.x,a.y-b.y,a.z-b.z);
function segmentDistance(start,end,point) {
  const dx=end.x-start.x,dy=end.y-start.y,dz=end.z-start.z,
    length=dx*dx+dy*dy+dz*dz,
    amount=length?Math.max(0,Math.min(1,((point.x-start.x)*dx+(point.y-start.y)*dy+(point.z-start.z)*dz)/length)):0;
  return Math.hypot(point.x-start.x-dx*amount,point.y-start.y-dy*amount,point.z-start.z-dz*amount);
}

test("only active personal records become searchable owner-local graph terms", () => {
  const terms=personalGraphTerms([
    personal(), personal({term_id:"personal_22222222222222222222222222222222",status:"proposed"}),
    personal({term_id:"personal_33333333333333333333333333333333",status:"deleted"}),
  ]);
  assert.equal(terms.length,1);
  assert.equal(terms[0].is_personal,true);
  assert.equal(terms[0].search_disabled,false);
  assert.equal(terms[0].recommended_search_query,"ballet arabesque pose drawing");
  assert.equal(terms[0].plain_meaning_ko,personal().plain_meaning_ko);
  assert.deepEqual(terms[0].reference_checkpoints,personal().reference_checkpoints_ko);
});

test("personal and public terms share the explicit selected-condition query", () => {
  const custom=personalGraphTerms([personal()])[0],publicTerm=ACTIVE_TERMS.find(term=>term.term_id==="pose_standing"),
    scope=createGraphSearchScope([...ACTIVE_TERMS,custom],[publicTerm.term_id,custom.term_id],custom.term_id);
  assert.equal(scope.focusedTerm.term_id,custom.term_id);
  assert.deepEqual(scope.selectedTerms.map(term=>term.term_id),[publicTerm.term_id,custom.term_id]);
  assert.match(scope.selectedQuery,/ballet arabesque pose/);
});

test("personal overlay adds one category parent without moving any public world coordinate", () => {
  const base=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,["pose_sitting","pose_contrapposto"]),
    before=coordinates(base), graph=attachPersonalTermOverlay(base,[personal()]);
  assert.deepEqual(Object.fromEntries(Object.entries(coordinates(graph)).filter(([id])=>before[id])),before);
  const node=graph.nodes.find(entry=>entry.id===personal().term_id);
  assert.equal(node.isPersonal,true);
  assert.equal(node.term.plain_meaning_ko,personal().plain_meaning_ko);
  assert.deepEqual(graph.edges.filter(edge=>edge.target===node.id),[{source:"category:pose",target:node.id,personal:true}]);
});

test("a personal slot stays fixed across additions, refreshes, and inactive records", () => {
  const base=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,[]),first=personal(),
    second=personal({term_id:"personal_22222222222222222222222222222222",layout_slot:1,label_ko:"개인 포즈 둘"});
  const alone=attachPersonalTermOverlay(base,[first]),together=attachPersonalTermOverlay(base,[first,second]),
    afterDelete=attachPersonalTermOverlay(base,[first,{...second,status:"deleted"}]);
  for(const graph of [together,afterDelete]) {
    const a=alone.nodes.find(node=>node.id===first.term_id),b=graph.nodes.find(node=>node.id===first.term_id);
    assert.deepEqual({x:b.x,y:b.y,z:b.z},{x:a.x,y:a.y,z:a.z});
  }
  assert.equal(afterDelete.nodes.some(node=>node.id===second.term_id),false);
});

test("representative personal slots avoid real 3-D node collisions and unrelated-node edge penetration", () => {
  const records=[];
  for(const [role,prefix] of [["body","1"],["pose","2"],["composition","3"],["perspective","4"]]) {
    for(let slot=0;slot<4;slot++) records.push(personal({role,layout_slot:slot,
      term_id:`personal_${prefix}${String(slot).padStart(31,"0")}`,label_ko:`${role} 개인 ${slot}`}));
  }
  const base=buildExpandedTermGraph(HOME_TERMS,ACTIVE_TERMS,["pose_sitting","pose_contrapposto"]),
    graph=attachPersonalTermOverlay(base,records),personalNodes=graph.nodes.filter(node=>node.isPersonal);
  assert.equal(personalNodes.length,16);
  for(let i=0;i<personalNodes.length;i++) for(let j=i+1;j<personalNodes.length;j++)
    assert.ok(distance(personalNodes[i],personalNodes[j])>=88,`${personalNodes[i].id} collides with ${personalNodes[j].id}`);
  for(const edge of graph.edges.filter(edge=>edge.personal)) {
    const start=graph.nodes.find(node=>node.id===edge.source),end=graph.nodes.find(node=>node.id===edge.target);
    for(const obstacle of graph.nodes) {
      if(obstacle.id===start.id||obstacle.id===end.id) continue;
      assert.ok(segmentDistance(start,end,obstacle)>=44,`${edge.target} edge penetrates ${obstacle.id}`);
    }
  }
});

test("graph UI identifies personal nodes and enables explicit selection and search", () => {
  const graphSource=readFileSync(new URL("../components/TermGraph.jsx",import.meta.url),"utf8"),
    pageSource=readFileSync(new URL("../app/page.jsx",import.meta.url),"utf8"),
    creatorSource=readFileSync(new URL("../components/PersonalTermCreator.jsx",import.meta.url),"utf8");
  assert.match(graphSource,/personalTerms=\[\]/);
  assert.match(graphSource,/attachPersonalTermOverlay/);
  assert.match(graphSource,/data-personal/);
  assert.match(graphSource,/내 용어/);
  assert.doesNotMatch(graphSource,/개인 용어 검색은 다음 단계/);
  assert.match(graphSource,/onToggle\(node\.id\)/);
  assert.match(pageSource,/personalGraphTerms\(personalTerms\)/);
  assert.match(pageSource,/setPersonalTerms/);
  assert.match(pageSource,/onItemsChange/);
  assert.match(creatorSource,/onItemsChange/);
});
