import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source=readFileSync(new URL('../components/TermGraph.jsx',import.meta.url),'utf8');

test('graph observes its panel and explains the latched readable-list fallback',()=>{
 assert.match(source,/assessGraphViewport/);
 assert.match(source,/ResizeObserver/);
 assert.match(source,/const scene=sceneRef\.current,root=rootRef\.current,target=scene\|\|root/);
 assert.match(source,/observer\.observe\(target\)/);
 assert.match(source,/height=window\.matchMedia\('\(max-width: 760px\)'\)\.matches\?360/);
 assert.match(source,/responsiveFallback/);
 assert.match(source,/좁은 그래프 공간에서 노드가 겹치지 않도록 목록으로 표시합니다/);
 assert.match(source,/패널을 넓힌 뒤 3D 보기를 선택하면 같은 선택과 펼침 상태로 돌아갑니다/);
});

test('safe desktop expansion stays in 3D while genuinely dense graphs retain the readable list fallback',()=>{
 assert.match(source,/const list=listRequested\|\|logicalGraph\.denseOverflow\|\|responsiveFallback/);
 assert.match(source,/const listUnavailable=logicalGraph\.denseOverflow\|\|\(list&&viewportAssessment\.unsafe\)/);
 assert.match(source,/expandedIds\.length===0&&viewportAssessment\.unsafe/);
 assert.match(source,/if\(viewportAssessment\.unsafe\) return/);
});
