import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const page = readFileSync(new URL("../app/page.jsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");

test("personal term control stays outside scrolling histories in the workspace drawer", () => {
  const drawer = page.slice(page.indexOf("<HistoryDrawer"), page.indexOf("</HistoryDrawer>"));
  const actions = drawer.indexOf('className="history-sidebar-actions"');
  const scroller = drawer.indexOf('className="history-sidebar-list"');
  const createButton = drawer.indexOf('className="personal-term-open"');

  assert.ok(actions >= 0, "workspace drawer needs a fixed action group");
  assert.ok(createButton > actions && createButton < scroller,
    "new-term button must be in the action group before the history scroll region");
  assert.doesNotMatch(page, /className="prompt-toolbar"/);
  assert.doesNotMatch(page, /UH케 그릴 건가요\?/);
  assert.match(css, /\.history-sidebar-actions\s*\{[^}]*flex-shrink:\s*0/s);
});
