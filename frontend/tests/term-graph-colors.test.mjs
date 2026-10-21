import test from 'node:test';
import assert from 'node:assert/strict';
import { GRAPH_CATEGORY_COLORS, graphCategoryColor } from '../lib/term-graph-colors.mjs';

test('graph categories use fixed distinct colors with a deterministic fallback',()=>{
 const roles=['body','pose','composition','perspective'];
 const colors=roles.map(graphCategoryColor);
 assert.equal(new Set(colors).size,roles.length);
 for(const [index,role] of roles.entries()) {
  assert.equal(colors[index],GRAPH_CATEGORY_COLORS[role]);
  assert.match(colors[index],/^#[0-9A-F]{6}$/i);
 }
 assert.equal(graphCategoryColor('unknown'),GRAPH_CATEGORY_COLORS.fallback);
 assert.equal(graphCategoryColor(),GRAPH_CATEGORY_COLORS.fallback);
 assert.equal(graphCategoryColor('pose'),graphCategoryColor('pose'));
});
