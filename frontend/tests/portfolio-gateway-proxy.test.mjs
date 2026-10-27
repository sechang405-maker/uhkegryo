import assert from "node:assert/strict";
import test from "node:test";

import {
  OFFLINE_FAILURE_CODE,
  PORTFOLIO_OFFLINE_MESSAGE,
  createPortfolioGatewayProxy,
} from "../lib/portfolio-gateway-proxy.mjs";

const SECRET = "a".repeat(48);

function configured(overrides = {}) {
  return {
    PORTFOLIO_GATEWAY_ORIGIN: "https://example-gateway.trycloudflare.com",
    PORTFOLIO_GATEWAY_SECRET: SECRET,
    ...overrides,
  };
}

test("portfolio gateway proxy uses only the configured HTTPS origin", async () => {
  let upstream;
  const proxy = createPortfolioGatewayProxy({
    env: configured(),
    fetchImpl: async (url, options) => {
      upstream = { url: String(url), options };
      return new Response("ok", { status: 200 });
    },
  });
  const response = await proxy(new Request(
    "https://portfolio.vercel.app/api/sessions?next=https://attacker.invalid",
    {
      headers: {
        "accept-encoding": "gzip, br",
        connection: "keep-alive",
        cookie: "session_id=browser-cookie",
        host: "portfolio.vercel.app",
        origin: "https://portfolio.vercel.app",
        "x-portfolio-gateway-secret": "attacker-controlled",
      },
    },
  ), "/api/sessions");

  assert.equal(response.status, 200);
  assert.equal(upstream.url,
    "https://example-gateway.trycloudflare.com/api/sessions?next=https%3A%2F%2Fattacker.invalid");
  assert.equal(upstream.options.headers.get("x-portfolio-gateway-secret"), SECRET);
  assert.equal(upstream.options.headers.get("origin"), "https://portfolio.vercel.app");
  assert.equal(upstream.options.headers.get("cookie"), "session_id=browser-cookie");
  assert.equal(upstream.options.headers.has("host"), false);
  assert.equal(upstream.options.headers.has("connection"), false);
  assert.equal(upstream.options.headers.has("accept-encoding"), false);
  assert.equal(upstream.options.redirect, "manual");
});

test("portfolio gateway proxy preserves status, body, and session cookie", async () => {
  const proxy = createPortfolioGatewayProxy({
    env: configured(),
    fetchImpl: async () => new Response(JSON.stringify({ session_id: "new" }), {
      status: 201,
      headers: {
        "content-type": "application/json",
        "set-cookie": "session_id=opaque; Path=/; Secure; HttpOnly; SameSite=Lax",
      },
    }),
  });
  const response = await proxy(new Request("https://portfolio.vercel.app/api/sessions", {
    method: "POST",
    body: "{}",
    headers: { "content-type": "application/json" },
  }), "/api/sessions");

  assert.equal(response.status, 201);
  assert.equal(response.headers.get("set-cookie"),
    "session_id=opaque; Path=/; Secure; HttpOnly; SameSite=Lax");
  assert.deepEqual(await response.json(), { session_id: "new" });
});

test("portfolio gateway proxy fails closed for invalid server configuration", async () => {
  const invalid = [
    configured({ PORTFOLIO_GATEWAY_ORIGIN: "http://example-gateway.trycloudflare.com" }),
    configured({ PORTFOLIO_GATEWAY_ORIGIN: "https://example.com/path" }),
    configured({ PORTFOLIO_GATEWAY_ORIGIN: "https://user@example.com" }),
    configured({ PORTFOLIO_GATEWAY_SECRET: "too-short" }),
    configured({ PORTFOLIO_GATEWAY_SECRET: "" }),
  ];
  for (const env of invalid) {
    let called = false;
    const proxy = createPortfolioGatewayProxy({ env, fetchImpl: async () => {
      called = true;
      return new Response("unexpected");
    } });
    const response = await proxy(
      new Request("https://portfolio.vercel.app/service-health"), "/service-health",
    );
    assert.equal(response.status, 503);
    assert.equal(called, false);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal((await response.json()).failure_code, OFFLINE_FAILURE_CODE);
  }
});

test("portfolio gateway proxy returns the exact offline response on network failure", async () => {
  const proxy = createPortfolioGatewayProxy({
    env: configured(),
    fetchImpl: async () => { throw new TypeError("private upstream details"); },
  });
  const response = await proxy(
    new Request("https://portfolio.vercel.app/service-health"), "/service-health",
  );
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), {
    detail: PORTFOLIO_OFFLINE_MESSAGE,
    failure_code: OFFLINE_FAILURE_CODE,
    retryable: false,
    user_message: PORTFOLIO_OFFLINE_MESSAGE,
  });
});

