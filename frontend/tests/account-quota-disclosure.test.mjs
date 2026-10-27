import assert from "node:assert/strict";
import test from "node:test";

const disclosure = await import("../lib/account-quota-disclosure.mjs").catch(() => ({}));

class FakeEventTarget {
  constructor() {
    this.listeners = new Map();
  }

  addEventListener(type, listener) {
    this.listeners.set(type, listener);
  }

  removeEventListener(type, listener) {
    if (this.listeners.get(type) === listener) this.listeners.delete(type);
  }

  emit(type, event = {}) {
    this.listeners.get(type)?.(event);
  }
}

test("account quota details start closed and open only after an explicit toggle", () => {
  assert.equal(typeof disclosure.createAccountQuotaDisclosureState, "function");
  assert.equal(typeof disclosure.reduceAccountQuotaDisclosure, "function");
  const initial = disclosure.createAccountQuotaDisclosureState();
  assert.equal(initial, false);
  assert.equal(disclosure.reduceAccountQuotaDisclosure(initial, { type: "toggle" }), true);
  assert.equal(disclosure.reduceAccountQuotaDisclosure(true, { type: "toggle" }), false);
});

test("dismissal closes details for refreshes, navigation, and explicit close actions", () => {
  assert.equal(typeof disclosure.reduceAccountQuotaDisclosure, "function");
  for (const type of ["dismiss", "refresh", "navigate"]) {
    assert.equal(disclosure.reduceAccountQuotaDisclosure(true, { type }), false);
  }
});

test("outside pointer, Escape, and page hide dismiss while inside pointer stays open", () => {
  assert.equal(typeof disclosure.bindAccountQuotaDismissal, "function");
  const documentTarget = new FakeEventTarget();
  const windowTarget = new FakeEventTarget();
  const inside = {};
  const outside = {};
  let dismissals = 0;
  const cleanup = disclosure.bindAccountQuotaDismissal({
    documentTarget,
    windowTarget,
    root: { contains: (target) => target === inside },
    onDismiss: () => { dismissals += 1; },
  });

  documentTarget.emit("pointerdown", { target: inside });
  documentTarget.emit("keydown", { key: "Enter" });
  assert.equal(dismissals, 0);
  documentTarget.emit("pointerdown", { target: outside });
  documentTarget.emit("keydown", { key: "Escape" });
  windowTarget.emit("pagehide");
  assert.equal(dismissals, 3);

  cleanup();
  documentTarget.emit("pointerdown", { target: outside });
  windowTarget.emit("pagehide");
  assert.equal(dismissals, 3);
});
