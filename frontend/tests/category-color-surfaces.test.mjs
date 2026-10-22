import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const graphSource=readFileSync(new URL('../components/TermGraph.jsx',import.meta.url),'utf8');
const pageSource=readFileSync(new URL('../app/page.jsx',import.meta.url),'utf8');
const css=readFileSync(new URL('../app/globals.css',import.meta.url),'utf8');

test('term list groups and rows receive their data category color',()=>{
 assert.match(graphSource,/graphCategoryColor/);
 assert.match(graphSource,/className="term-graph-list-category"/);
 assert.match(graphSource,/--category-color':graphCategoryColor\(category\.role\)/);
 assert.match(graphSource,/data-category=\{category\.role\}/);
 assert.match(css,/\.term-graph-list-category\s*\{[^}]*border:2px solid var\(--category-color\)/s);
 assert.match(css,/\.term-graph-list-category\s*>\s*div\s*\{[^}]*background:[^;}]*--category/s);
});

test('result rows, badges, controls and cards share the graph category palette',()=>{
 assert.match(pageSource,/graphCategoryColor/);
 assert.match(pageSource,/--category-color':\s*graphCategoryColor\(role\)/);
 assert.match(pageSource,/className="pin-gallery-category-badge"/);
 assert.match(css,/\.pin-gallery-row\s*\{[^}]*--category-color/s);
 assert.match(css,/\.pin-gallery-category-badge,\s*\.active-term-badge\s*\{[^}]*background:[^;}]*--category/s);
 assert.match(css,/\.pin-gallery-card\s*\{[^}]*border:\s*3px solid var\(--category-color\)/s);
 assert.match(css,/\.category-search-actions\s*\{[^}]*border:\s*3px solid var\(--category-color\)/s);
});
