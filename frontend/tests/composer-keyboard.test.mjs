import test from "node:test";
import assert from "node:assert/strict";
import { shouldSubmitOnEnter } from "../lib/agent-submit.mjs";

test("Enter submits, Shift+Enter and composition keep editing", () => {
  assert.equal(shouldSubmitOnEnter({ key: "Enter" }), true);
  for (const event of [{ key: "Enter", shiftKey: true }, { key: "Enter", isComposing: true },
    { key: "Enter", nativeEvent: { isComposing: true } }, { key: "Enter", keyCode: 229 },
    { key: "Enter", nativeEvent: { keyCode: 229 } }, { key: "a" }, { key: "Enter", repeat: true }]) {
    assert.equal(shouldSubmitOnEnter(event), false);
  }
  assert.equal(shouldSubmitOnEnter({ key: "Enter" }, true), false);
});
