import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const graphSource=readFileSync(new URL('../components/TermGraph.jsx',import.meta.url),'utf8');
const pageSource=readFileSync(new URL('../app/page.jsx',import.meta.url),'utf8');

test('graph UI names the focused-term and selected-condition search scopes',()=>{
 assert.match(graphSource,/현재 설명 중인 용어/);
 assert.match(graphSource,/현재 용어만 검색/);
 assert.match(graphSource,/선택 조건 \{selected\.length\}개/);
 assert.match(graphSource,/선택 조건 전체 검색/);
 assert.match(graphSource,/펼치기는 관련 용어를 보여 줄 뿐 선택 조건에 포함되지 않습니다/);
 assert.match(graphSource,/disabled=\{!selectedSearchQuery\}/);
 assert.match(graphSource,/onClick=\{\(\)=>onSearch\(focused\)\}/);
});

test('page derives one selected query and shares it with header and graph actions',()=>{
 assert.match(pageSource,/createGraphSearchScope/);
 assert.match(pageSource,/graphSearchScope\.selectedQuery/);
 assert.match(pageSource,/selectedSearchQuery=\{graphSearchScope\.selectedQuery\}/);
 assert.match(pageSource,/선택 조건 \{graphSearchScope\.selectedTerms\.length\}개 전체 검색/);
});
