import test from "node:test";
import assert from "node:assert/strict";
import { getRecommendedSearchQuery, combineRecommendedSearchQueries } from "../lib/recommended-query.mjs";

test("TERM_CARD 미리보기의 저장 검색어를 우선 표시한다", () => {
  assert.equal(
    getRecommendedSearchQuery({ recommended_search_query: "contrapposto pose drawing" }),
    "contrapposto pose drawing",
  );
});

test("실제 응답의 결정론 search_url에서 사이트 제한을 제외한 검색어를 복원한다", () => {
  assert.equal(
    getRecommendedSearchQuery({ search_url: "https://www.google.com/search?q=site%3Akr.pinterest.com%2Fpin%2F+front+view+drawing" }),
    "front view drawing",
  );
  assert.equal(getRecommendedSearchQuery({ search_url: "not-a-url" }), null);
});

test('selected cards combine complete query phrases once and retain one drawing suffix',()=>{
 const body={recommended_search_query:'hourglass body proportion reference drawing'},pose={recommended_search_query:'standing pose reference drawing'},view={recommended_search_query:'front view drawing'};
 assert.equal(combineRecommendedSearchQueries([]),null);
 assert.equal(combineRecommendedSearchQueries([body]),body.recommended_search_query);
 assert.equal(combineRecommendedSearchQueries([body,pose,view,pose]),'hourglass body proportion standing pose front view reference drawing');
 assert.equal(combineRecommendedSearchQueries([view,{recommended_search_query:'side view drawing'}]),'front view side view reference drawing');
 assert.equal(combineRecommendedSearchQueries([{},view]),'front view drawing');
});
