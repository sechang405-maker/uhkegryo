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

test("초기 포트폴리오 샘플은 지정한 체형만 보여 주고 이미지를 요청하지 않는다", () => {
  const slots = createMindMapSlots(DEMO_JOB.result.reference_plan.terms);

  assert.equal(DEMO_JOB.job_status, "completed");
  assert.match(DEMO_REQUEST_TEXT, /허리가 들어간/);
  assert.equal(slots.filter((slot) => slot.term).length, 1);
  assert.deepEqual(slots.map((slot) => slot.terms.length), [1, 0, 0, 0, 0]);
  assert.equal(slots[0].term.label_ko, "모래시계형");
  assert.deepEqual(slots[0].term.pins, []);
});

