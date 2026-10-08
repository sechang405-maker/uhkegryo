import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import MarkdownAnswer from "../components/MarkdownAnswer.mjs";

const render = (text) => renderToStaticMarkup(createElement(MarkdownAnswer, { text }));

test("제목·굵게·목록·인용을 Markdown 태그로 표시한다", () => {
  const html = render("### 관찰 포인트\n\n**슬림** 체형입니다.\n\n- 몸통 폭\n- 팔다리 굵기\n\n> 의상과 구분하세요.");
  assert.match(html, /<h3>관찰 포인트<\/h3>/);
  assert.match(html, /<strong>슬림<\/strong>/);
  assert.match(html, /<ul>/);
  assert.match(html, /<li>몸통 폭<\/li>/);
  assert.match(html, /<blockquote>/);
});

test("원시 HTML·이미지·iframe·클릭 가능한 링크를 허용하지 않는다", () => {
  const html = render('<script>alert(1)</script>\n\n<img src="https://example.com/a.png">\n\n<iframe src="https://example.com"></iframe>\n\n![외부 이미지](https://example.com/b.png)\n\n[위험 링크](javascript:alert(1))\n\n[출처](https://example.com)');
  assert.doesNotMatch(html, /<(script|img|iframe|a)\b/);
  assert.doesNotMatch(html, /src=|href=/);
  assert.match(html, /출처/);
});

test("기존 일반 텍스트도 유지하고 큰 제목은 대화 크기로 제한한다", () => {
  assert.match(render("기존 설명입니다."), /<p>기존 설명입니다.<\/p>/);
  assert.match(render("# 제목"), /<h3>제목<\/h3>/);
  assert.doesNotMatch(render("# 제목"), /<h1>/);
});
