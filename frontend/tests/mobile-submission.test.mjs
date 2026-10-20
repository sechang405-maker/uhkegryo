import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

// Execute the actual page handler without rendering JSX or calling a live API.
const source = readFileSync(new URL("../app/page.jsx", import.meta.url), "utf8");
const start = source.indexOf("  async function submit(text)");
const end = source.indexOf("  function handleGalleryScroll", start);
assert.ok(start >= 0 && end > start);
const handler = source.slice(start, end);

async function submitScenario(mode) {
  const state = { boardMutations: [], panel: "conversation", error: "", input: "마른 캐릭터", submitting: false };
  const noop = () => {};
  const context = {
    activeUsageRef: { current: { message_count: 19, message_limit: 20, remaining_messages: 1, can_submit: true } },
    applyUsage: usage => { if (usage) state.usage = usage; },
    refreshUsage: () => { state.usageRefreshed = true; },
    conversationBusy: false,
    visitScreen: noop, crypto: { randomUUID: () => "navigation-test" }, sessionLoadRef: { current: 0 }, screenGenerationRef: { current: 0 },
    AbortController, submissionRequestRef: { current: null },
    deleteInFlightRef: { current: false },
    submitInFlightRef: { current: false },
    gallerySelectionRef: { current: { reset: () => state.boardMutations.push("reset"), begin: noop } },
    submissionRef: { current: {
      isPending: () => false,
      submit: async (_text, options) => {
        state.submittedUsage = options.usage;
        if (mode === "submit_exception") throw new Error("network test");
        if (mode === 'quota') return { ok: false, error: 'limit', failureCode: 'session_message_limit_reached', usage: { message_count: 20, can_submit: false } };
        if (mode === 'quota_without_usage') return { ok: false, error: 'limit', failureCode: 'session_message_limit_reached', retryable: false };
        if (mode === 'twentieth') return { ok: true, jobId: 'twentieth-result', usage: { message_count: 20, can_submit: false } };
        return mode === "error_response" ? { ok: false, error: "접수 실패" }
          : { ok: true, jobId: "test", pollAfterMs: 100 };
      },
    } },
    historyLoaderRef: { current: { cancel: noop } },
    validateRequestText: () => null,
    termSearchControllerRef: { current: null },
    resetSketchSearches: noop, refreshSessions: noop,
    setMobilePanel: (value) => { state.panel = value; },
    setTermGuide: noop, uiDemoEnabled: false,
    pollerRef: { current: null }, pendingRequestRef: { current: "" }, selectedJobRef: { current: null },
    sessionId: mode === "create_exception" ? null : "test",
    sessionIdRef: { current: mode === "create_exception" ? null : "test" },
    createConversation: async () => {
      if (mode === "create_exception") throw new Error("network test");
      return { session_id: "new-session", created_at: "2026-10-07T01:00:00Z" };
    },
    setError: (value) => { state.error = value; },
    setRequestText: (value) => { state.input = value; },
    setIsSubmitting: (value) => { state.submitting = value; },
    setBoardView: () => state.boardMutations.push("view"), setPollError: noop, setSubmission: noop, setJob: () => state.boardMutations.push("job"),
    setSelectedTermId: () => state.boardMutations.push("selection"), setSessionId: noop, setSessions: noop, setTurns: noop,
  };
  vm.createContext(context);
  vm.runInContext(handler + "\nthis.runSubmit = submit;", context);
  await context.runSubmit(state.input);
  return state;
}

for (const mode of ["error_response", "create_exception", "submit_exception"]) {
  test(`mobile submission failure returns to conversation: ${mode}`, async () => {
    const state = await submitScenario(mode);
    assert.equal(state.panel, "conversation");
    assert.equal(state.input, "마른 캐릭터");
    assert.ok(state.error);
    assert.equal(state.submitting, false);
  });
}

test("successful mobile submission keeps the conversation visible and clears the input", async () => {
  const state = await submitScenario("success");
  assert.equal(state.panel, "conversation");
  assert.equal(state.input, "");
  assert.equal(state.error, "");
  assert.equal(state.submitting, false);
});


test("submitting chat keeps the current board and selection until an explicit reference result arrives", async () => {
 const state = await submitScenario("success"); assert.deepEqual(state.boardMutations, []);
});

test('the twentieth result is accepted and server quota updates without replacing the board', async () => {
 const state = await submitScenario('twentieth');
 assert.equal(state.usage.message_count, 20); assert.equal(state.input, '');
 assert.equal(state.submittedUsage.message_count, 19); assert.deepEqual(state.boardMutations, []);
});

test('a server quota rejection updates remaining usage and retains input and gallery', async () => {
 const state = await submitScenario('quota');
 assert.equal(state.usage.can_submit, false); assert.ok(state.input); assert.equal(state.error, 'limit');
 assert.deepEqual(state.boardMutations, []);
});

test('quota rejection without totals refreshes authoritative session usage', async () => {
 const state = await submitScenario('quota_without_usage');
 assert.equal(state.usageRefreshed, true); assert.ok(state.input); assert.deepEqual(state.boardMutations, []);
});
