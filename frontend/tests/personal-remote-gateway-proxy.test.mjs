import assert from "node:assert/strict";
import test from "node:test";

import { createPersonalRemoteGatewayProxy } from "../lib/personal-remote-gateway-proxy.mjs";

const PUBLIC = "https://owner-preview.vercel.app";
const GATEWAY = "https://owner-gateway.example";
const SECRET = "synthetic-server-secret-" + "x".repeat(32);

function configured(overrides = {}) {
  return {
    PERSONAL_REMOTE_TEST: "1",
    PERSONAL_REMOTE_PUBLIC_ORIGIN: PUBLIC,
    PERSONAL_REMOTE_GATEWAY_ORIGIN: GATEWAY,
    PERSONAL_REMOTE_GATEWAY_SECRET: SECRET,
    ...overrides,
  };
}

test("personal proxy pins public and gateway origins and replaces attacker gateway headers", async () => {
  let upstream;
  const proxy = createPersonalRemoteGatewayProxy({
    env: configured(),
    fetchImpl: async (url, options) => {
      upstream = { url: String(url), options };
      return Response.json({ ok: true });
    },
  });
  const response = await proxy(new Request(`${PUBLIC}/api/agent?next=https://evil.test`, {
    method: "POST",
    headers: {
      origin: PUBLIC,
      host: "evil.test",
      cookie: "session_id=opaque",
      "content-type": "application/json",
      "x-personal-remote-gateway-secret": "attacker-value",
      "x-forwarded-host": "evil.test",
    },
    body: "{}",
  }), "/api/agent");

  assert.equal(response.status, 200);
  assert.equal(upstream.url, `${GATEWAY}/api/agent?next=https%3A%2F%2Fevil.test`);
  assert.equal(upstream.options.headers.get("x-personal-remote-gateway-secret"), SECRET);
  assert.equal(upstream.options.headers.get("origin"), PUBLIC);
  assert.equal(upstream.options.headers.get("cookie"), "session_id=opaque");
  assert.equal(upstream.options.headers.has("host"), false);
  assert.equal(upstream.options.headers.has("x-forwarded-host"), false);
  assert.equal((await response.text()).includes(SECRET), false);
});

test("personal proxy fails closed for missing config public host spoof and CSRF", async () => {
  const cases = [
    [configured({ PERSONAL_REMOTE_GATEWAY_SECRET: "" }), new Request(`${PUBLIC}/api/agent`)],
    [configured({ PERSONAL_REMOTE_GATEWAY_SECRET: "é".repeat(40) }), new Request(`${PUBLIC}/api/agent`)],
    [configured(), new Request("https://evil.test/api/agent")],
    [configured(), new Request(`${PUBLIC}/api/agent`, { method: "POST", body: "{}" })],
    [configured(), new Request(`${PUBLIC}/api/agent`, {
      method: "POST", body: "{}", headers: { origin: "https://evil.test" },
    })],
  ];
  for (const [env, request] of cases) {
    let called = false;
    const proxy = createPersonalRemoteGatewayProxy({
      env, fetchImpl: async () => { called = true; return new Response("unexpected"); },
    });
    const response = await proxy(request, "/api/agent");
    assert.equal(response.status, 503);
    assert.equal(called, false);
  }
});

test("personal proxy preserves secure cookies and permits only expected auth redirects", async () => {
  const cookie = "session_id=opaque; Path=/; Secure; HttpOnly; SameSite=Lax";
  const responses = [
    new Response(null, { status: 307, headers: { location: "https://accounts.google.com/o/oauth2/v2/auth" } }),
    new Response(null, { status: 307, headers: { location: `${PUBLIC}/` } }),
    new Response(null, { status: 307, headers: { location: "https://evil.test/steal" } }),
    new Response("ok", { status: 200, headers: { "set-cookie": cookie } }),
  ];
  const proxy = createPersonalRemoteGatewayProxy({
    env: configured(), fetchImpl: async () => responses.shift(),
  });

  const start = await proxy(new Request(`${PUBLIC}/api/auth/google/start`), "/api/auth/google/start");
  assert.equal(start.status, 307);
  assert.equal(start.headers.get("location"), "https://accounts.google.com/o/oauth2/v2/auth");

  const callback = await proxy(
    new Request(`${PUBLIC}/api/auth/google/callback?state=s&code=c`),
    "/api/auth/google/callback",
  );
  assert.equal(callback.status, 307);
  assert.equal(callback.headers.get("location"), `${PUBLIC}/`);

  const rejected = await proxy(new Request(`${PUBLIC}/api/auth/me`), "/api/auth/me");
  assert.equal(rejected.status, 503);

  const me = await proxy(new Request(`${PUBLIC}/api/auth/me`), "/api/auth/me");
  assert.equal(me.headers.get("set-cookie"), cookie);
  assert.equal(me.headers.get("x-personal-remote-gateway-secret"), null);
});

test("anonymous portfolio proxy mode cannot select the personal proxy", async () => {
  let called = false;
  const proxy = createPersonalRemoteGatewayProxy({
    env: configured({ PERSONAL_REMOTE_TEST: "0", PORTFOLIO_MODE: "1" }),
    fetchImpl: async () => { called = true; return new Response("unexpected"); },
  });
  assert.equal((await proxy(new Request(`${PUBLIC}/api/agent`), "/api/agent")).status, 503);
  assert.equal(called, false);

  const mixed = createPersonalRemoteGatewayProxy({
    env: configured({ PORTFOLIO_MODE: "1" }),
    fetchImpl: async () => { called = true; return new Response("unexpected"); },
  });
  assert.equal((await mixed(new Request(`${PUBLIC}/api/agent`), "/api/agent")).status, 503);
});

test("personal remote mode disables the direct backend rewrite", async () => {
  const previous = {
    personal: process.env.PERSONAL_REMOTE_TEST,
    portfolioGateway: process.env.PORTFOLIO_GATEWAY_PROXY,
    demo: process.env.NEXT_PUBLIC_UI_DEMO,
  };
  process.env.PERSONAL_REMOTE_TEST = "1";
  process.env.PORTFOLIO_GATEWAY_PROXY = "0";
  process.env.NEXT_PUBLIC_UI_DEMO = "0";
  try {
    const { default: config } = await import(`../next.config.mjs?personal=${Date.now()}`);
    assert.deepEqual(await config.rewrites(), []);
  } finally {
    if (previous.personal === undefined) delete process.env.PERSONAL_REMOTE_TEST;
    else process.env.PERSONAL_REMOTE_TEST = previous.personal;
    if (previous.portfolioGateway === undefined) delete process.env.PORTFOLIO_GATEWAY_PROXY;
    else process.env.PORTFOLIO_GATEWAY_PROXY = previous.portfolioGateway;
    if (previous.demo === undefined) delete process.env.NEXT_PUBLIC_UI_DEMO;
    else process.env.NEXT_PUBLIC_UI_DEMO = previous.demo;
  }
});

test("personal service health stays on the authenticated gateway boundary", async () => {
  let target;
  const proxy = createPersonalRemoteGatewayProxy({
    env: configured(),
    fetchImpl: async (url) => { target = String(url); return Response.json({ status: "ok" }); },
  });
  const response = await proxy(new Request(`${PUBLIC}/service-health`), "/service-health");
  assert.equal(response.status, 200);
  assert.equal(target, `${GATEWAY}/health`);
});
