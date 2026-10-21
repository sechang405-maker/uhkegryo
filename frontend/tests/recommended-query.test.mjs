import test from "node:test";
import assert from "node:assert/strict";
import { getRecommendedSearchQuery, combineRecommendedSearchQueries, createGraphSearchScope } from "../lib/recommended-query.mjs";

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

test('graph search scope keeps the focused term separate from explicit selections',()=>{
 const body={term_id:'body_hourglass',label_ko:'모래시계형',recommended_search_query:'hourglass body reference drawing'};
 const pose={term_id:'pose_standing',label_ko:'스탠딩',recommended_search_query:'standing pose reference drawing'};
 const view={term_id:'composition_front',label_ko:'프론트 뷰',recommended_search_query:'front view drawing'};
 const terms=[body,pose,view];

 const empty=createGraphSearchScope(terms,[],body.term_id);
 assert.equal(empty.focusedTerm,body);
 assert.deepEqual(empty.selectedTerms,[]);
 assert.equal(empty.selectedQuery,null);

 const one=createGraphSearchScope(terms,[pose.term_id],body.term_id);
 assert.equal(one.focusedTerm,body);
 assert.deepEqual(one.selectedTerms,[pose]);
 assert.equal(one.selectedQuery,pose.recommended_search_query);

 const many=createGraphSearchScope(terms,[pose.term_id,'missing',view.term_id,pose.term_id],body.term_id);
 assert.equal(many.focusedTerm,body);
 assert.deepEqual(many.selectedTerms,[pose,view]);
 assert.equal(many.selectedQuery,'standing pose front view reference drawing');

 const focusChanged=createGraphSearchScope(terms,[pose.term_id,view.term_id],view.term_id);
 assert.equal(focusChanged.focusedTerm,view);
 assert.deepEqual(focusChanged.selectedTerms,many.selectedTerms);
 assert.equal(focusChanged.selectedQuery,many.selectedQuery);

 const deselected=createGraphSearchScope(terms,[view.term_id],view.term_id);
 assert.deepEqual(deselected.selectedTerms,[view]);
 assert.equal(deselected.selectedQuery,view.recommended_search_query);
});
