import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const panel = readFileSync(new URL("../components/ConversationPanel.jsx", import.meta.url), "utf8");
const page = readFileSync(new URL("../app/page.jsx", import.meta.url), "utf8");

test("a stopped accepted job offers an explicit status-only recheck", () => {
  assert.match(panel, /상태 다시 확인/);
  assert.match(panel, /onRetryStatus\(turn\.id\)/);
  assert.match(panel, /polling_error/);
  assert.match(page, /onRetryStatus=\{retryTurnStatus\}/);
  const start = page.indexOf("  function retryTurnStatus(turnId)");
  const end = page.indexOf("  function openTurn(turn)", start);
  assert.ok(start >= 0 && end > start);
  const handler = page.slice(start, end);
  assert.match(handler, /resumeTurnPolling/);
  assert.doesNotMatch(handler, /submit\(|\/api\/agent|POST/);
});
