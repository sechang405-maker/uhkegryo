import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../app/page.jsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
const drawerComponent = readFileSync(new URL("../components/HistoryDrawer.jsx", import.meta.url), "utf8");

function drawerContents() {
  const start = page.indexOf("<HistoryDrawer");
  const end = page.indexOf("</HistoryDrawer>", start);
  assert.notEqual(start, -1, "history drawer must exist");
  assert.notEqual(end, -1, "history drawer must close");
  return page.slice(start, end);
}

test("account and workspace actions live inside the left history drawer", () => {
  const drawer = drawerContents();
  assert.match(drawer, /className="history-sidebar-actions"/);
  assert.match(drawer, /aria-label="계정 및 주요 작업"/);
  assert.match(drawer, /<AuthAccessControl\s*\/>/);
  assert.match(drawer, /<AccountQuota\s*\/>/);
  assert.match(drawer, /className="personal-term-open"/);

  const beforeDrawer = page.slice(page.indexOf("<main"), page.indexOf("<HistoryDrawer"));
  assert.doesNotMatch(beforeDrawer, /<AuthAccessControl|<AccountQuota/);
  assert.doesNotMatch(page, /className="prompt-toolbar"/);
});

test("opening the personal term editor dismisses the drawer first", () => {
  const drawer = drawerContents();
  assert.match(drawer, /onClick=\{openPersonalTermCreator\}/);
  assert.match(page, /function openPersonalTermCreator\(\)\s*\{\s*setMenuOpen\(false\);\s*setPersonalTermOpen\(true\);\s*\}/s);
});

test("the expanded drawer is named as the whole workspace menu", () => {
  assert.match(drawerComponent, /aria-label="UH케그려 메뉴"/);
  assert.match(drawerComponent, /aria-label="메뉴 닫기"/);
  assert.match(drawerComponent, /aria-label=\{`UH케그려 메뉴 \$\{open \? "닫기" : "열기"\}`\}/);
});

test("drawer actions use panel layout while only conversation history scrolls", () => {
  assert.match(css, /\.history-sidebar-actions\s*\{[^}]*flex-shrink:\s*0[^}]*padding:[^}]*border-bottom:[^}]*\}/s);
  assert.match(css, /\.history-sidebar-actions\s+\.auth-access-control\s*\{[^}]*position:\s*static[^}]*width:\s*100%[^}]*\}/s);
  assert.match(css, /\.history-sidebar-actions\s+\.account-quota\s*\{[^}]*position:\s*static[^}]*max-width:\s*none[^}]*\}/s);
  assert.match(css, /\.history-sidebar-actions\s+\.personal-term-open\s*\{[^}]*width:\s*100%[^}]*min-height:\s*44px[^}]*\}/s);
  assert.match(css, /@media\s*\(max-width:\s*760px\)[^\n]*\.history-sidebar-actions\s*\{\s*padding:\s*10px 8px/);
});
