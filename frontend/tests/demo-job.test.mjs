import test from "node:test";
import assert from "node:assert/strict";
import { DEMO_JOB, DEMO_REQUEST_TEXT } from "../lib/demo-job.mjs";
import * as homeCatalog from "../lib/home-catalog.mjs";
import { createMindMapSlots } from "../lib/term-mind-map.mjs";

test("실제 모드 홈은 검색 job 없이 검수된 다섯 카테고리를 제공한다", () => {
  assert.ok(Array.isArray(homeCatalog.HOME_TERMS));
  const slots = createMindMapSlots(homeCatalog.HOME_TERMS);
  assert.deepEqual(slots.map((slot) => slot.terms.length), [3, 3, 3, 3, 2]);
  assert.equal(slots[0].term.label_ko, "모래시계형");
});

test("홈 카드는 실제 검색 결과인 것처럼 더미 핀이나 답변을 포함하지 않는다", () => {
  assert.ok(Array.isArray(homeCatalog.HOME_TERMS));
  for (const term of homeCatalog.HOME_TERMS) {
    assert.deepEqual(term.pins, []);
    assert.equal(term.answer_text, undefined);
    assert.ok(term.recommended_search_query.endsWith(" drawing"));
  }
});

test("UI 미리보기 Job은 카탈로그의 검수 완료 TERM_CARD 다섯 역할을 제공한다", () => {
  const slots = createMindMapSlots(DEMO_JOB.result.reference_plan.terms);

  assert.equal(DEMO_JOB.job_status, "completed");
  assert.match(DEMO_REQUEST_TEXT, /허리가 들어간/);
  assert.equal(slots.filter((slot) => slot.term).length, 5);
  assert.deepEqual(slots.map((slot) => slot.terms.length), [3, 3, 3, 3, 2]);
  assert.equal(slots[0].term.label_ko, "모래시계형");
  assert.equal(slots[3].term.term_id, "perspective_three_point");
  assert.equal(slots[4].term.label_ko, "삼분할 구도");
  assert.equal(slots[4].term.term_id, "composition_rule_of_thirds");
});
