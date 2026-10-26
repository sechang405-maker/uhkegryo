import test from "node:test";
import assert from "node:assert/strict";
import * as view from "../lib/result-view.mjs";
import { createMindMapSlots } from "../lib/term-mind-map.mjs";

const term = (role, extra = {}) => ({ role, term_id: role, label_ko: role, ...extra });
const completed = (agent_status, extra = {}) => ({ job_status: "completed", result: { agent_status, ...extra } });

test("결과는 완료된 success/partial_result에만 노출한다", () => {
  for (const status of ["success", "partial_result"]) {
    assert.equal(view.resultTerms(completed(status, { reference_plan: { terms: [term("body")] } })).length, 1);
  }
  for (const status of ["needs_clarification", "out_of_scope", "unsafe_input"]) {
    assert.deepEqual(view.resultTerms(completed(status, { reference_plan: { terms: [term("body")] } })), []);
  }
  assert.deepEqual(view.resultTerms({ job_status: "searching" }), []);
});

test("역할 부분 갱신은 유지 역할의 이전 검색 데이터와 Pin을 보존한다", () => {
  const previousBody = term("body", { term_id: "old-body", pins: [{ pin_id: "body-pin", status: "available" }] });
  const previousPose = term("pose", { term_id: "old-pose", pins: [{ pin_id: "old-pose-pin", status: "available" }] });
  const replacedPose = term("pose", { term_id: "new-pose", pins: [{ pin_id: "new-pose-pin", status: "available" }] });
  const turns = [
    { id: "first", job: { job_id: "first", job_status: "completed", result: { agent_status: "success", reference_plan: { terms: [previousBody, previousPose] } } } },
    { id: "second", job: { job_id: "second", job_status: "completed", result: {
      agent_status: "success",
      reference_plan: { terms: [term("body", { term_id: "new-body" }), replacedPose] },
      reference_update: { replaced_roles: ["pose"], preserved_roles: ["body"], removed_roles: [] },
    } } },
  ];

  const rendered = view.renderedResultTerms(turns[1].job, turns);
  assert.deepEqual(rendered, [previousBody, replacedPose]);
  assert.equal(rendered[0].pins[0].pin_id, "body-pin");
  assert.equal(rendered[1].pins[0].pin_id, "new-pose-pin");
});

test("역할 부분 갱신은 삭제 역할을 제외하고 확인 질문에서는 이전 보드를 유지한다", () => {
  const body = term("body", { term_id: "body", pins: [{ pin_id: "body-pin", status: "available" }] });
  const pose = term("pose", { term_id: "pose", pins: [{ pin_id: "pose-pin", status: "available" }] });
  const first = { job_id: "first", job_status: "completed", result: { agent_status: "success", reference_plan: { terms: [body, pose] } } };
  const removed = { job_id: "removed", job_status: "completed", result: {
    agent_status: "success", reference_plan: { terms: [body] },
    reference_update: { replaced_roles: [], preserved_roles: ["body"], removed_roles: ["pose"] },
  } };
  const clarification = { job_id: "clarify", job_status: "completed", result: {
    agent_status: "needs_clarification", reference_plan: null,
    reference_update: { replaced_roles: [], preserved_roles: ["body", "pose"], removed_roles: [] },
  } };

  assert.deepEqual(view.renderedResultTerms(removed, [{ job: first }, { job: removed }]), [body]);
  assert.deepEqual(view.renderedResultTerms(clarification, [{ job: first }, { job: clarification }]), [body, pose]);
});

test("실패와 빈 카테고리 및 접근 불가 Pin을 순서대로 보존한다", () => {
  const rows = view.createGalleryRows(createMindMapSlots([
    term("body", { reason_codes: ["PIN_SEARCH_UNAVAILABLE"], pins: [] }),
    term("pose", { reason_codes: ["PIN_RESULTS_EMPTY"], pins: [] }),
    term("view", { pins: [{ pin_id: "deleted", status: "deleted", thumbnail_url: "old" }] }),
  ]));
  assert.deepEqual(rows.map((row) => row.role), ["body", "pose", "composition"]);
  assert.match(view.roleNotice(rows[0].term), /가져오지/);
  assert.match(view.roleNotice(rows[1].term), /없습니다/);
  assert.equal(rows[2].pins[0].pin_id, "deleted");
  assert.equal(view.showThumbnail(rows[2].pins[0]), false);
  assert.equal(view.showThumbnail({ status: "available", thumbnail_url: "image" }), true);
  assert.equal(view.showThumbnail({ status: "available", thumbnail_url: null }), false);
});

test("each card keeps its own gallery and eight-pin limit, including empty siblings", () => {
  const pins = Array.from({ length: 10 }, (_, index) => ({ pin_id: String(index), status: "available", thumbnail_url: "image" }));
  const rows = view.createGalleryRows(createMindMapSlots([term("pose"), term("pose", { term_id: "second", pins })]));
  assert.deepEqual(rows.map((row) => row.term.term_id), ["pose", "second"]);
  assert.deepEqual(rows[0].pins, []);
  assert.deepEqual(rows[1].pins.map((pin) => pin.pin_id), ["0", "1", "2", "3", "4", "5", "6", "7"]);
});

test("실패 안내와 추가 질문은 결과 상태에 맞게 분리한다", () => {
  assert.equal(view.resultUserMessage({ job_status: "failed", failure: { user_message: "실패 안내" } }), "실패 안내");
  for (const status of ["out_of_scope", "unsafe_input", "reference_guidance"]) assert.equal(view.resultUserMessage(completed(status, { user_message: "입력 안내" })), "입력 안내");
  assert.equal(view.resultUserMessage(completed("needs_clarification")), null);
  assert.deepEqual(view.clarificationChoices({}), []);
  assert.deepEqual(view.clarificationChoices({ clarification_choices: [{ label: "앉기", request_text: "앉은 캐릭터" }] }), [{ label: "앉기", request_text: "앉은 캐릭터" }]);
});



test("term updates preserve a sibling in the same category with its own gallery", () => {
  const first = term("pose", { term_id: "pose-a", pins: [{ pin_id: "a" }] });
  const second = term("pose", { term_id: "pose-b", pins: [{ pin_id: "b" }] });
  const replacement = term("pose", { term_id: "pose-c", pins: [{ pin_id: "c" }] });
  const previous = { job_id: "old", ...completed("success", { reference_plan: { terms: [first, second] } }) };
  const current = { job_id: "new", ...completed("success", {
    reference_plan: { terms: [replacement] },
    reference_update: { preserved_term_ids: ["pose-b"], replaced_term_ids: ["pose-c"], removed_term_ids: ["pose-a"],
      preserved_roles: [], replaced_roles: ["pose"], removed_roles: [] },
  }) };
  assert.deepEqual(view.renderedResultTerms(current, [{ job: previous }, { job: current }]), [second, replacement]);
});

test("legacy category updates keep every preserved and replaced card", () => {
  const bodyA = term("body", { term_id: "body-a" });
  const bodyB = term("body", { term_id: "body-b" });
  const poseA = term("pose", { term_id: "pose-a" });
  const poseB = term("pose", { term_id: "pose-b" });
  const previous = { job_id: "old", ...completed("success", { reference_plan: { terms: [bodyA, bodyB] } }) };
  const current = { job_id: "new", ...completed("success", {
    reference_plan: { terms: [poseA, poseB] },
    reference_update: { preserved_roles: ["body"], replaced_roles: ["pose"], removed_roles: [] },
  }) };
  assert.deepEqual(view.renderedResultTerms(current, [{ job: previous }, { job: current }]), [bodyA, bodyB, poseA, poseB]);
});

 test("temporary and unknown pin statuses have a retry message", () => {
  assert.equal(view.pinUnavailableMessage({status: "unavailable"}), "이미지를 일시적으로 불러오지 못했습니다. 다시 시도해 주세요.");
  assert.equal(view.pinUnavailableMessage({status: "future-status"}), view.pinUnavailableMessage({status: "unavailable"}));
  assert.equal(view.pinUnavailableMessage({status: "deleted"}), "삭제된 핀입니다.");
 });

test('full current merged plan preserves cards with preceding reference outside page',()=>{
 const body={term_id:'body',role:'body',pins:[{pin_id:'new'}]},pose={term_id:'pose',role:'pose'};
 const job=completed('success',{reference_plan:{terms:[body,pose]},reference_update:{preserved_term_ids:['body'],replaced_term_ids:['pose']}});
 assert.deepEqual(view.renderedResultTerms(job,[]),[body,pose]);
});
test('legacy role board uses bounded preceding reference context outside page',()=>{
 const body=term('body'),pose=term('pose');
 const job=completed('success',{reference_plan:{terms:[pose]},reference_update:{preserved_roles:['body'],replaced_roles:['pose']}});
 assert.deepEqual(view.renderedResultTerms(job,[],completed('success',{reference_plan:{terms:[body]}})),[body,pose]);
});

test("image availability notice distinguishes partial, total, empty, and provider failures", () => {
  const available = { pin_id: "ok", status: "available", thumbnail_url: "https://i.pinimg.com/ok.jpg" };
  const unavailable = { pin_id: "bad", status: "unavailable", thumbnail_url: null };
  assert.match(view.imageAvailabilityNotice({ pins: [available, unavailable] }), /1/);
  assert.match(view.imageAvailabilityNotice({ pins: [unavailable, { ...unavailable, pin_id: "bad-2" }] }), /\ubaa8\ub4e0/);
  assert.match(view.imageAvailabilityNotice({ pins: [available] }, { "term:ok": true }, "term"), /\ubaa8\ub4e0/);
  assert.equal(view.imageAvailabilityNotice({ pins: [], reason_codes: ["PIN_RESULTS_EMPTY"] }), null);
  assert.equal(view.imageAvailabilityNotice({ pins: [], reason_codes: ["PIN_SEARCH_UNAVAILABLE"] }), null);
  assert.equal(view.imageAvailabilityNotice({ pins: [unavailable], reason_codes: ["PIN_SEARCH_UNAVAILABLE"] }), null);
  assert.equal(view.imageAvailabilityNotice({ pins: [available] }), null);
});
