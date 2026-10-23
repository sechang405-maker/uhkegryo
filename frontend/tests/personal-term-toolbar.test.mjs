import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const page = readFileSync(new URL("../app/page.jsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");

test("personal term control stays outside the scrolling conversation history", () => {
  const aside = page.slice(page.indexOf('<aside id="conversation-panel"'));
  const toolbar = aside.indexOf('className="prompt-toolbar"');
  const scroller = aside.indexOf('className="panel-top"');
  const createButton = aside.indexOf('className="personal-term-open"');

  assert.ok(toolbar >= 0, "conversation panel needs a fixed toolbar");
  assert.ok(createButton > toolbar && createButton < scroller,
    "new-term button must be in the toolbar before the scroll region");
  assert.doesNotMatch(page, /UH케 그릴 건가요\?/);
  assert.match(css, /\.prompt-toolbar\s*\{[^}]*flex:\s*0 0 auto/s);
});
