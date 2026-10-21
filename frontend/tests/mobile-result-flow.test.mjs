import test from "node:test";
import assert from "node:assert/strict";

import {
  createMobileResultOrigin,
  resolveMobileResult,
} from "../lib/mobile-result-flow.mjs";

const current = (overrides = {}) => ({
  requestId: "job-2",
  sessionId: "session-1",
  screenGeneration: 7,
  panelRevision: 3,
  ...overrides,
});

test("a result from the unchanged mobile screen opens automatically", () => {
  const origin = createMobileResultOrigin(current());

  assert.deepEqual(resolveMobileResult(origin, current()), {
    accepted: true,
    shouldOpen: true,
  });
});

test("an explicit panel choice keeps the current panel and asks the user to open the result", () => {
  const origin = createMobileResultOrigin(current());

  assert.deepEqual(resolveMobileResult(origin, current({ panelRevision: 4 })), {
    accepted: true,
    shouldOpen: false,
  });
});

test("a completion from another request, conversation, or screen is ignored", () => {
  const origin = createMobileResultOrigin(current());

  for (const changed of [
    { requestId: "job-older" },
    { sessionId: "session-2" },
    { screenGeneration: 8 },
  ]) {
    assert.deepEqual(resolveMobileResult(origin, current(changed)), {
      accepted: false,
      shouldOpen: false,
    });
  }
});

test("origins are immutable snapshots so rapid searches cannot rewrite an older request", () => {
  const mutable = current();
  const origin = createMobileResultOrigin(mutable);
  mutable.requestId = "job-3";
  mutable.panelRevision = 9;

  assert.equal(origin.requestId, "job-2");
  assert.equal(origin.panelRevision, 3);
  assert.equal(Object.isFrozen(origin), true);
});
