import test from "node:test";
import assert from "node:assert/strict";
import { applySketchResult, restoreOriginalSearch, searchFixedTerm } from "../lib/term-search.mjs";
import * as searches from "../lib/term-search.mjs";

const term = { term_id: "body_hourglass", role: "body" };

test("모든 재검색 모드는 실제 API 응답의 새 핀으로 교체한다", async () => {
  const base = { ...term, pins: [{ pin_id: "dummy" }], plain_meaning_ko: "설명" };
  for (const suffix of ["drawing", "sketch", "mannequinization"]) {
    const calls = [];
    const updated = await searches.searchTermMode(base, suffix, { fetchImpl: async (url, options) => {
      calls.push({ url, body: JSON.parse(options.body) });
      return { ok: true, json: async () => ({ ...term, search_url: `https://www.google.com/search?q=hourglass+${suffix}`,
        pins: [{ pin_id: suffix, status: "available", thumbnail_url: `https://i.pinimg.com/${suffix}.jpg` }] }) };
    } });
    assert.deepEqual(calls, [{ url: "/api/term-search", body: { term_id: term.term_id, suffix } }]);
    assert.equal(updated.pins[0].pin_id, suffix);
    assert.equal(updated.plain_meaning_ko, "설명");
    assert.equal(base.pins[0].pin_id, "dummy");
  }
});

test("재검색 실패는 이전 결과를 성공으로 바꾸지 않으며 같은 모드도 다시 호출한다", async () => {
  let count = 0;
  const fetchImpl = async () => { count++; return { ok: true, json: async () => ({ ...term,
    pins: [{ pin_id: String(count), status: "available", thumbnail_url: "https://i.pinimg.com/new.jpg" }] }) }; };
  const first = await searches.searchTermMode(term, "drawing", { fetchImpl });
  const second = await searches.searchTermMode(first, "drawing", { fetchImpl });
  assert.equal(second.pins[0].pin_id, "2");
  await assert.rejects(searches.searchTermMode(first, "sketch", { fetchImpl: async () => ({ ok: true,
    json: async () => ({ ...term, pins: [], reason_codes: ["PIN_SEARCH_UNAVAILABLE"] }) }) }), /기존 이미지/);
  assert.equal(first.pins[0].pin_id, "1");
});

test("일반 복원은 해당 카드 덮어쓰기만 제거하고 다른 행과 원본은 유지한다", () => {
  const original = { ...term, pins: [{ pin_id: "original" }], recommended_search_query: "hourglass drawing" };
  const searches = { [term.term_id]: { suffix: "mannequinization", term: { ...original, pins: [{ pin_id: "new" }] }, loading: true },
    pose: { suffix: "sketch" } };
  const restored = restoreOriginalSearch(searches, term.term_id);
  assert.equal(restored[term.term_id], undefined);
  assert.equal(restored.pose, searches.pose);
  assert.equal(searches[term.term_id].suffix, "mannequinization");
  assert.equal((restored[term.term_id]?.term || original).pins[0].pin_id, "original");
  assert.equal((restored[term.term_id]?.term || original).recommended_search_query, "hourglass drawing");
});

test("단일 검색은 term_id만 보내고 job/기록 API를 호출하지 않는다", async () => {
  const calls = [];
  const signal = new AbortController().signal;
  const result = await searchFixedTerm(term, { signal, fetchImpl: async (url, options) => {
    calls.push({ url, options });
    return { ok: true, json: async () => ({ ...term, pins: [] }) };
  } });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/term-search");
  assert.deepEqual(JSON.parse(calls[0].options.body), { term_id: term.term_id });
  assert.equal(calls[0].options.signal, signal);
  assert.equal(result.term_id, term.term_id);
});

test("다른 카드 응답과 HTTP 실패는 정상 결과로 표시하지 않는다", async () => {
  await assert.rejects(searchFixedTerm(term, { fetchImpl: async () => ({
    ok: true, json: async () => ({ ...term, term_id: "wrong", pins: [] }),
  }) }), /일치하지/);
  await assert.rejects(searchFixedTerm(term, { fetchImpl: async () => ({
    ok: false, json: async () => ({ detail: "검색이 진행 중입니다." }),
  }) }), /진행 중/);
});

test("백엔드 미연결의 비 JSON 오류도 읽을 수 있는 검색 실패로 표시한다", async () => {
  await assert.rejects(searchFixedTerm(term, { fetchImpl: async () => ({
    ok: false, json: async () => { throw new SyntaxError("not JSON"); },
  }) }), /검색 결과를 가져오지/);
});

test("스케치 요청은 suffix만 추가하고 자유 검색어는 보내지 않는다", async () => {
  await searchFixedTerm(term, { suffix: "sketch", fetchImpl: async (url, options) => {
    assert.deepEqual(JSON.parse(options.body), { term_id: term.term_id, suffix: "sketch" });
    return { ok: true, json: async () => ({ ...term, pins: [] }) };
  } });
});

test("스케치 성공은 이미지와 검색어만 변경하며 설명은 유지한다", () => {
  const base = { ...term, plain_meaning_ko: "기존 설명", selection_reason: "기존 근거",
    reference_checkpoints: ["확인"], pins: [{ pin_id: "old" }], recommended_search_query: "hourglass drawing" };
  const result = { ...term, pins: [{ status: "available", thumbnail_url: "https://i.pinimg.com/test.jpg" }],
    search_url: "https://www.google.com/search?q=site%3Akr.pinterest.com%2Fpin%2F+hourglass+sketch" };
  const updated = applySketchResult(base, result);
  assert.equal(updated.plain_meaning_ko, base.plain_meaning_ko);
  assert.equal(updated.selection_reason, base.selection_reason);
  assert.deepEqual(updated.reference_checkpoints, base.reference_checkpoints);
  assert.equal(updated.search_url, result.search_url);
  assert.equal(updated.recommended_search_query, null);
  assert.equal(base.pins[0].pin_id, "old");
  assert.throws(() => applySketchResult(base, { pins: [], reason_codes: ["PIN_SEARCH_UNAVAILABLE"] }), /기존 이미지/);
  assert.throws(() => applySketchResult(base, { pins: [], reason_codes: ["PIN_RESULTS_EMPTY"] }), /기존 이미지/);
});

test("도형화는 같은 카드에 mannequinization을 보내고 설명을 유지한다", async () => {
  const base = { ...term, plain_meaning_ko: "기존 설명", recommended_search_query: "hourglass sketch", pins: [{ pin_id: "old" }] };
  const result = await searchFixedTerm(base, { suffix: "mannequinization", fetchImpl: async (url, options) => {
    assert.deepEqual(JSON.parse(options.body), { term_id: term.term_id, suffix: "mannequinization" });
    return { ok: true, json: async () => ({ ...term, search_url: "https://www.google.com/search?q=hourglass+mannequinization",
      pins: [{ status: "available", thumbnail_url: "https://i.pinimg.com/test.jpg" }] }) };
  } });
  const updated = applySketchResult(base, result);
  assert.equal(updated.plain_meaning_ko, base.plain_meaning_ko);
  assert.equal(updated.search_url, result.search_url);
  assert.equal(base.recommended_search_query, "hourglass sketch");
});
