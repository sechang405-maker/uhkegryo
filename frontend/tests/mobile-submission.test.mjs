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
  const state = { panel: "conversation", error: "", input: "마른 캐릭터", submitting: false };
  const noop = () => {};
  const context = {
    conversationBusy: false,
    submissionRef: { current: {
      isPending: () => false,
      submit: async () => {
        if (mode === "submit_exception") throw new Error("network test");
        return mode === "error_response" ? { ok: false, error: "접수 실패" }
          : { ok: true, jobId: "test", pollAfterMs: 100 };
      },
    } },
    historyLoaderRef: { current: { cancel: noop } },
    validateRequestText: () => null,
    termSearchControllerRef: { current: null },
    resetSketchSearches: noop,
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
    setBoardView: noop, setPollError: noop, setSubmission: noop, setJob: noop,
    setSelectedTermId: noop, setSessionId: noop, setSessions: noop, setTurns: noop,
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

test("successful mobile submission keeps references and clears the input", async () => {
  const state = await submitScenario("success");
  assert.equal(state.panel, "reference");
  assert.equal(state.input, "");
  assert.equal(state.error, "");
  assert.equal(state.submitting, false);
});
