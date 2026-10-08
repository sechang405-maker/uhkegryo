import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { LoadingIndicator, ImageSearchLoading, LoadingImage } from "../components/LoadingIndicator.mjs";

test("대기 문구는 읽을 수 있고 장식 점은 별도로 읽히지 않는다", () => {
  const html = renderToStaticMarkup(createElement(LoadingIndicator, { label: "검색 중", size: "small" }));
  assert.match(html, /role="status"/);
  assert.match(html, /검색 중/);
  assert.match(html, /aria-hidden="true"/);
  assert.match(html, /data-size="small"/);
});

test("이미지 검색 대기는 여덟 장의 숨겨진 자리 표시자를 제공한다", () => {
  const html = renderToStaticMarkup(createElement(ImageSearchLoading, { label: "자료 조회 중" }));
  assert.equal((html.match(/class="pin-skeleton"/g) || []).length, 8);
  assert.match(html, /자료 조회 중/);
  assert.match(html, /aria-hidden="true"/);
});

test("이미지가 아직 로드되지 않았으면 이미지 공간에 대기 표시를 제공한다", () => {
  const html = renderToStaticMarkup(createElement(LoadingImage, { src: "/test.jpg", alt: "포즈", size: "small" }));
  assert.match(html, /data-loading="true"/);
  assert.match(html, /이미지 불러오는 중/);
  assert.match(html, /alt="포즈"/);
});
