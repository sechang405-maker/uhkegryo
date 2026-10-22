import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ACTIVE_TERMS, HOME_TERMS } from "../lib/home-catalog.mjs";
import TermGuide from "../components/TermGuide.mjs";
import { GRAPH_HELP_ITEMS } from "../lib/term-graph-help.mjs";

test("홈 카드 36개는 뜻·관찰점·주의 사항으로 안내할 수 있다", () => {
  assert.equal(HOME_TERMS.length, 36);
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

test("all active terms expose definitions instead of internal search instructions", () => {
  assert.equal(ACTIVE_TERMS.length, 82);
  for (const term of ACTIVE_TERMS) {
    assert.ok(term.plain_meaning_ko?.trim(), `${term.term_id} has no description`);
    assert.doesNotMatch(term.plain_meaning_ko, /레퍼런스를 찾을 때|단서를 우선 확인|팀 작성 초안/,
      `${term.term_id} exposes an internal search instruction`);
    assert.match(term.plain_meaning_ko, /입니다\./,
      `${term.term_id} is not a user-facing definition`);
  }
});

test("collapsible graph help distinguishes selection, expansion, search, and 3D controls", () => {
  assert.deepEqual(GRAPH_HELP_ITEMS.map((item) => item.label), ["선택", "펼치기", "검색", "3D 조작"]);
  const text = GRAPH_HELP_ITEMS.map((item) => item.description).join(" ");
  assert.match(text, /검색 조건/);
  assert.match(text, /선택되지/);
  assert.match(text, /현재 용어|선택 조건 전체/);
  assert.match(text, /드래그.*회전/);
  assert.match(text, /휠.*확대.*축소/);
});
