import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source=readFileSync(new URL('../components/TermGraph.jsx',import.meta.url),'utf8');

test('graph observes its panel without replacing the requested 3D view on desktop',()=>{
 assert.match(source,/assessGraphViewport/);
 assert.match(source,/ResizeObserver/);
 assert.match(source,/const scene=sceneRef\.current,root=rootRef\.current,target=scene\|\|root/);
 assert.match(source,/observer\.observe\(target\)/);
 assert.match(source,/height=window\.matchMedia\('\(max-width: 760px\)'\)\.matches\?360/);
 assert.doesNotMatch(source,/responsiveFallback/);
});

test('desktop keeps 3D and a user can leave the mobile list even when the projection is crowded',()=>{
 assert.match(source,/const list=listRequested\|\|logicalGraph\.denseOverflow/);
 assert.match(source,/const listUnavailable=logicalGraph\.denseOverflow/);
 assert.doesNotMatch(source,/expandedIds\.length===0&&viewportAssessment\.unsafe/);
 assert.doesNotMatch(source,/if\(viewportAssessment\.unsafe\) return/);
 assert.match(source,/max-width: 760px/);
});
