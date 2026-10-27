import assert from "node:assert/strict";
import test from "node:test";

test("portfolio build returns 404 for private account routes", async () => {
  process.env.PORTFOLIO_MODE = "1";
  const { proxy } = await import(`../proxy.js?portfolio=${Date.now()}`);
  const response = proxy(new Request("https://portfolio.example/admin"));
  assert.equal(response.status, 404);
  assert.equal(await response.text(), "Not Found");
});

test("PC portfolio gateway fails closed unless the Vercel secret matches", async () => {
  process.env.PORTFOLIO_MODE = "1";
  process.env.PORTFOLIO_GATEWAY_REQUIRED = "1";
  process.env.PORTFOLIO_GATEWAY_SECRET = "s".repeat(48);
  const { proxy } = await import(`../proxy.js?gateway=${Date.now()}`);

  const missing = proxy(new Request("https://gateway.example/api/sessions"));
  assert.equal(missing.status, 404);
  assert.equal(await missing.text(), "Not Found");

  const wrong = proxy(new Request("https://gateway.example/service-health", {
    headers: { "x-portfolio-gateway-secret": "x".repeat(48) },
  }));
  assert.equal(wrong.status, 404);

  const accepted = proxy(new Request("https://gateway.example/api/sessions", {
    headers: { "x-portfolio-gateway-secret": "s".repeat(48) },
  }));
  assert.equal(accepted.headers.get("x-middleware-next"), "1");
  assert.equal(accepted.headers.has("x-portfolio-gateway-secret"), false);
});

test("PC portfolio gateway returns unavailable when its secret is misconfigured", async () => {
  process.env.PORTFOLIO_MODE = "1";
  process.env.PORTFOLIO_GATEWAY_REQUIRED = "1";
  process.env.PORTFOLIO_GATEWAY_SECRET = "short";
  const { proxy } = await import(`../proxy.js?misconfigured=${Date.now()}`);
  const response = proxy(new Request("https://gateway.example/service-health"));
  assert.equal(response.status, 503);
  assert.equal(response.headers.get("cache-control"), "no-store");
});
