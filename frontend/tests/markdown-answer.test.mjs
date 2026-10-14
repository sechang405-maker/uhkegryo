import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import MarkdownAnswer from "../components/MarkdownAnswer.mjs";

const render = (text) => renderToStaticMarkup(createElement(MarkdownAnswer, { text }));
const renderJob = (job) => renderToStaticMarkup(createElement(MarkdownAnswer, { job }));
const cardJob = (terms, answer_text = '') => ({ job_status: 'completed', result: {
  agent_status: 'success', answer_text, reference_plan: { terms },
} });

test('카드별 검증된 이름을 h2 제목으로 표시하고 해당 설명을 같은 묶음에 둔다', () => {
  const html = renderJob(cardJob([
    { term_id: 'body_hourglass', label_ko: '모래시계형', plain_meaning_ko: '허리가 들어간 체형입니다.', selection_reason: '어깨와 골반 비율을 참고해요.' },
    { term_id: 'pose_contrapposto', label_ko: '콘트라포스토', plain_meaning_ko: '어깨와 골반의 반대 기울기를 봅니다.' },
  ], '두 조건을 함께 관찰하세요.'));
  const sections = [...html.matchAll(/<section\b[^>]*>(.*?)<\/section>/gs)].map(match => match[1]);
  assert.match(sections[0], /<h2[^>]*>모래시계형<\/h2>/);
  assert.match(sections[0], /허리가 들어간 체형입니다/);
  assert.match(sections[0], /어깨와 골반 비율을 참고해요/);
  assert.doesNotMatch(sections[0], /반대 기울기/);
  assert.match(sections[1], /<h2[^>]*>콘트라포스토<\/h2>/);
  assert.match(sections[1], /반대 기울기/);
  assert.doesNotMatch(sections[1], /허리가 들어간/);
  assert.match(html, /종합 설명/);
  assert.ok(html.indexOf('종합 설명') > html.indexOf('반대 기울기'));
  assert.match(html, /두 조건을 함께 관찰하세요/);
});

test('단일 카드와 저장된 이전 구조도 렌더링하고 없는 종합 설명을 만들지 않는다', () => {
  const job = cardJob([{term_id:'view_front', label_ko:'정면', plain_meaning_ko:'앞에서 바라보는 시점입니다.'}]);
  const restored = JSON.parse(JSON.stringify(job));
  assert.equal(renderJob(restored), renderJob(job));
  const html = renderJob(restored);
  assert.equal((html.match(/<h2\b/g) || []).length, 1);
  assert.match(html, /앞에서 바라보는 시점/);
  assert.doesNotMatch(html, /종합 설명|백엔드 연결 후/);
});

test('카드 없는 과거 답변·질문·실패·기억 답변에는 카드 제목을 생성하지 않는다', () => {
  for (const job of [
    cardJob([], '기존 일반 답변'),
    {job_status:'completed',result:{agent_status:'needs_clarification',clarifying_question:'어느 다리가 지지하나요?'}},
    {job_status:'failed',failure:{user_message:'다시 시도해 주세요.'}},
    {job_status:'completed',result:{agent_status:'memory_answer',memory_answer:'이전 대화의 답변입니다.'}},
  ]) {
    const html = renderJob(job);
    assert.doesNotMatch(html, /<h2\b|answer-card-section|종합 설명/);
    assert.match(html, /기존 일반 답변|어느 다리가|다시 시도|이전 대화/);
  }
});

test('카드 이름은 모델 Markdown으로 재해석하지 않고 설명의 HTML·링크를 실행하지 않는다', () => {
  const html = renderJob(cardJob([{term_id:'safe',label_ko:'[카드](javascript:alert(1)) <img src=x>',
    plain_meaning_ko:'<script>alert(1)</script>\n\n[링크](javascript:alert(1))\n\n![이미지](https://evil.example/x)',
  }], '<iframe src="https://evil.example"></iframe>\n\n[외부](https://evil.example)'));
  assert.doesNotMatch(html, /<(script|img|iframe|a)\b|href=/);
  assert.match(html, /&lt;img src=x&gt;/);
  assert.match(html, /<h2[^>]*>\[카드\]/);
});

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

