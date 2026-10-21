import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

import { createMobileResultOrigin, resolveMobileResult } from "../lib/mobile-result-flow.mjs";

const source = readFileSync(new URL("../app/page.jsx", import.meta.url), "utf8");
const presentStart = source.indexOf("  function presentMobileResult(origin, notice)");
const presentEnd = source.indexOf("  function openMobileResult()", presentStart);
const searchStart = source.indexOf("  async function openTermSearch(term)");
const searchEnd = source.indexOf("  function resetSketchSearches", searchStart);
assert.ok(presentStart >= 0 && presentEnd > presentStart && searchStart >= 0 && searchEnd > searchStart);

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function setup() {
  const searches = [];
  const state = { panel: "reference", notice: null, search: null, screen: 0, revision: 0 };
  const sessionIdRef = { current: "session-1" };
  const screenGenerationRef = { current: 0 };
  const mobilePanelRevisionRef = { current: 0 };
  const termSearchControllerRef = { current: null };
  const termSearchOriginRef = { current: null };
  const noop = () => {};
  const context = {
    createMobileResultOrigin,
    resolveMobileResult,
    crypto: { randomUUID: () => `request-${searches.length + 1}` },
    AbortController,
    sessionIdRef,
    screenGenerationRef,
    mobilePanelRevisionRef,
    termSearchControllerRef,
    termSearchOriginRef,
    uiDemoEnabled: false,
    gallerySelectionRef: { current: { reset: noop } },
    visitScreen: () => { screenGenerationRef.current += 1; state.screen = screenGenerationRef.current; state.notice = null; },
    setTermGuide: noop,
    resetSketchSearches: noop,
    setSelectedTermId: noop,
    setActiveGalleryTermId: noop,
    setFailedThumbnails: noop,
    setBoardView: noop,
    setMobilePanel: value => { state.panel = value; },
    setMobileResultNotice: value => { state.notice = typeof value === "function" ? value(state.notice) : value; },
    setTermSearch: value => { state.search = value; },
    demoTerm: noop,
    showThumbnail: () => false,
    applySketchResult: (_term, result) => result,
    searchFixedTerm: () => {
      const request = deferred();
      searches.push(request);
      return request.promise;
    },
  };
  vm.createContext(context);
  vm.runInContext(source.slice(presentStart, presentEnd) + source.slice(searchStart, searchEnd) + "\nthis.open = openTermSearch;", context);
  return { state, searches, context, screenGenerationRef, mobilePanelRevisionRef };
}

const term = { term_id: "sitting", label_ko: "시팅", pins: [] };
const result = { ...term, pins: [{ pin_id: "pin-1" }], reason_codes: [] };

test("a finished fixed-term search opens references when the user kept the automatic conversation view", async () => {
  const { state, searches, context } = setup();
  const pending = context.open(term);
  assert.equal(state.panel, "conversation");
  searches[0].resolve(result);
  await pending;
  assert.equal(state.panel, "reference");
  assert.equal(state.notice, null);
  assert.equal(state.search.loading, false);
});

test("an explicit tab choice keeps the panel and exposes a result action", async () => {
  const { state, searches, context, mobilePanelRevisionRef } = setup();
  const pending = context.open(term);
  state.panel = "conversation";
  mobilePanelRevisionRef.current += 1;
  searches[0].resolve(result);
  await pending;
  assert.equal(state.panel, "conversation");
  assert.equal(state.notice.targetPanel, "reference");
  assert.equal(state.notice.actionLabel, "결과 보기");
});

test("a rapid second search invalidates the older completion", async () => {
  const { state, searches, context } = setup();
  const first = context.open(term);
  const second = context.open({ ...term, term_id: "standing", label_ko: "스탠딩" });
  searches[0].resolve(result);
  await first;
  assert.equal(state.search.term.term_id, "standing");
  searches[1].resolve({ ...result, term_id: "standing", label_ko: "스탠딩" });
  await second;
  assert.equal(state.search.term.term_id, "standing");
  assert.equal(state.panel, "reference");
});

test("a fixed-term failure opens or announces the scoped error without showing another request", async () => {
  const { state, searches, context, mobilePanelRevisionRef } = setup();
  const pending = context.open(term);
  mobilePanelRevisionRef.current += 1;
  searches[0].reject(new Error("검색 실패"));
  await pending;
  assert.equal(state.panel, "conversation");
  assert.equal(state.notice.targetPanel, "reference");
  assert.equal(state.notice.actionLabel, "오류 확인");
  assert.equal(state.search.error, "검색 실패");
});
