import assert from "node:assert/strict";
import test from "node:test";

test("portfolio build returns 404 for private account routes", async () => {
  process.env.PORTFOLIO_MODE = "1";
  const { proxy } = await import(`../proxy.js?portfolio=${Date.now()}`);
  const response = proxy();
  assert.equal(response.status, 404);
  assert.equal(await response.text(), "Not Found");
});
