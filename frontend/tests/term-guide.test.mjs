import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { HOME_TERMS } from "../lib/home-catalog.mjs";
import TermGuide from "../components/TermGuide.mjs";

test("홈 카드 14개는 뜻·관찰점·주의 사항으로 안내할 수 있다", () => {
  assert.equal(HOME_TERMS.length, 14);
  for (const term of HOME_TERMS) {
    const html = renderToStaticMarkup(createElement(TermGuide, { term }));
    assert.ok(term.plain_meaning_ko);
    assert.ok(term.reference_checkpoints.length);
    assert.match(html, /UH · 용어 안내/);
    assert.ok(html.includes(term.label_ko));
    assert.ok(!html.includes(term.term_id));
    assert.ok(!html.includes("UH · 답변"));
  }
});

test("콘트라포스토의 검수된 혼동 주의 사항을 표시한다", () => {
  const term = HOME_TERMS.find((entry) => entry.term_id === "pose_contrapposto");
  const html = renderToStaticMarkup(createElement(TermGuide, { term }));
  assert.match(html, /헷갈리기 쉬운 점/);
  assert.ok(html.includes(term.cautions[0]));
});

test("안내가 없으면 표시하지 않고 HTML은 실행하지 않는다", () => {
  assert.equal(renderToStaticMarkup(createElement(TermGuide)), "");
  const html = renderToStaticMarkup(createElement(TermGuide, { term: {
    label_ko: "예시", plain_meaning_ko: "<script>test</script>",
  } }));
  assert.match(html, /&lt;script&gt;/);
  assert.ok(!html.includes("<script>"));
});
