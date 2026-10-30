import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("public portfolio UI disables personal term generation with an honest notice", () => {
  const page = readFileSync(new URL("../app/page.jsx", import.meta.url), "utf8");
  assert.match(page, /NEXT_PUBLIC_PORTFOLIO_MODE/);
  assert.match(page, /portfolioMode\s*&&/);
  assert.match(page, /personal-term-disabled-notice/);
  assert.match(page, /0\s*\/\s*6/);
  assert.match(page, /!portfolioMode\s*&&\s*<PersonalTermCreator/);
  assert.match(page, /!portfolioMode\s*&&\s*<AuthAccessControl/);
});
