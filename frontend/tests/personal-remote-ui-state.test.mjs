import assert from "node:assert/strict";
import test from "node:test";

import * as conversation from "../lib/server-conversation.mjs";

const authState = await import("../lib/auth-state.mjs").catch(() => ({}));
const response = (body, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

test("normal pre-login 401 becomes anonymous while forbidden and offline auth stay errors", async () => {
  assert.equal(typeof authState.readAuthState, "function");
  assert.deepEqual(
    await authState.readAuthState({ fetchImpl: async () => response({}, 401) }),
    { state: "anonymous" },
  );
  assert.equal(await authState.readAuthState({ fetchImpl: async () => response({}, 404) }), null);
  assert.deepEqual(
    await authState.readAuthState({
      fetchImpl: async () => response({ state: "authenticated", account_id: "owner" }),
    }),
    { state: "authenticated", account_id: "owner" },
  );
  for (const status of [403, 503]) {
    await assert.rejects(authState.readAuthState({ fetchImpl: async () => response({}, status) }));
  }
});

test("only a real auth identity transition requests conversation restoration", () => {
  assert.equal(typeof authState.createAuthStateTracker, "function");
  const transitions = [];
  const update = authState.createAuthStateTracker((next) => transitions.push(next));
  assert.equal(update({ state: "anonymous" }), false);
  assert.equal(update({ state: "anonymous" }), false);
  assert.equal(update({ state: "authenticated", account_id: "owner" }), true);
  assert.equal(update({ state: "authenticated", account_id: "owner" }), false);
  assert.equal(update({ state: "anonymous" }), true);
  assert.deepEqual(transitions.map((item) => item.state), ["authenticated", "anonymous"]);
});

test("auth transition subscription cleans up and avoids duplicate restore handlers", () => {
  assert.equal(typeof authState.bindAuthStateChange, "function");
  const target = new EventTarget();
  let restores = 0;
  const cleanup = authState.bindAuthStateChange(target, () => { restores += 1; });
  target.dispatchEvent(new Event(authState.AUTH_STATE_EVENT));
  assert.equal(restores, 1);
  cleanup();
  target.dispatchEvent(new Event(authState.AUTH_STATE_EVENT));
  assert.equal(restores, 1);
});

test("anonymous bootstrap stops after health and profile without showing restore failure", async () => {
  assert.equal(typeof conversation.bootstrapConversation, "function");
  const calls = [];
  const result = await conversation.bootstrapConversation({ fetchImpl: async (url) => {
    calls.push(url);
    if (url === "/service-health") return response({ status: "ok" });
    if (url === "/api/local/profile") return response({}, 401);
    assert.fail(`unexpected anonymous request ${url}`);
  } });
  assert.deepEqual(result, {
    authenticated: false,
    persistent: false,
    restored: { sessionId: null, turns: [] },
  });
  assert.deepEqual(calls, ["/service-health", "/api/local/profile"]);
});

test("authenticated empty history is ready while 403 and 503 remain failures", async () => {
  assert.equal(typeof conversation.bootstrapConversation, "function");
  const calls = [];
  const result = await conversation.bootstrapConversation({ fetchImpl: async (url) => {
    calls.push(url);
    if (url === "/service-health") return response({ status: "ok" });
    if (url === "/api/local/profile") return response({ persistent: false });
    if (url === "/api/sessions?limit=1") return response({ items: [] });
    assert.fail(`unexpected authenticated request ${url}`);
  } });
  assert.equal(result.authenticated, true);
  assert.equal(result.persistent, false);
  assert.deepEqual(result.restored, { sessionId: null, turns: [] });
  assert.deepEqual(calls, ["/service-health", "/api/local/profile", "/api/sessions?limit=1"]);

  for (const status of [403, 503]) {
    await assert.rejects(
      conversation.bootstrapConversation({ fetchImpl: async (url) => (
        url === "/service-health" ? response({ status: "ok" }) : response({}, status)
      ) }),
      (error) => error.message === conversation.RESTORE_ERROR,
    );
  }
  await assert.rejects(
    conversation.bootstrapConversation({ fetchImpl: async () => response({}, 503) }),
    (error) => error.message === conversation.SERVICE_UNAVAILABLE_ERROR,
  );
});
