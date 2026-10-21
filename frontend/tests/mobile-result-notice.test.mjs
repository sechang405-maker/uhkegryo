import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const page = readFileSync(new URL("../app/page.jsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
const termSearch = page.slice(
  page.indexOf("  async function openTermSearch(term)"),
  page.indexOf("  function resetSketchSearches", page.indexOf("  async function openTermSearch(term)")),
);

test("fixed-term search completion is routed through the scoped mobile result flow", () => {
  assert.match(termSearch, /createMobileResultOrigin/);
  assert.match(termSearch, /presentMobileResult/);
  assert.match(termSearch, /termSearchOriginRef\.current/);
});

test("mobile navigation exposes an accessible result notice and explicit open action", () => {
  assert.match(page, /mobile-result-notice/);
  assert.match(page, /aria-live="polite"/);
  assert.match(page, /openMobileResult/);
  assert.match(page, /chooseMobilePanel\("reference"\)/);
  assert.match(css, /\.mobile-result-notice/);
  assert.match(css, /button\[data-has-notice="true"\]/);
});
