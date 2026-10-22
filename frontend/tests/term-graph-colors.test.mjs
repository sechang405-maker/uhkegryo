import test from 'node:test';
import assert from 'node:assert/strict';
import { GRAPH_CATEGORY_COLORS, graphCategoryColor, graphNodeColor } from '../lib/term-graph-colors.mjs';

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

test('detail nodes use a stable softer tone while parents keep the category color',()=>{
 const roles=['body','pose','composition','perspective'];
 for(const role of roles) {
  const parent=graphNodeColor(role,false);
  const detail=graphNodeColor(role,true);
  assert.equal(parent,graphCategoryColor(role));
  assert.notEqual(detail,parent);
  assert.match(detail,/^#[0-9A-F]{6}$/i);
  assert.equal(graphNodeColor(role,true),detail,'detail color must be deterministic');
 }
 assert.equal(graphNodeColor('unknown',false),GRAPH_CATEGORY_COLORS.fallback);
 assert.notEqual(graphNodeColor('unknown',true),GRAPH_CATEGORY_COLORS.fallback);
});

test('approved parent and child palettes match the final 3D mockup',()=>{
 assert.deepEqual(Object.fromEntries(['body','pose','composition','perspective'].map(role=>[role,graphNodeColor(role,false)])),{
  body:'#56C7D9',pose:'#F4A261',composition:'#B892FF',perspective:'#6FD3A3',
 });
 assert.deepEqual(Object.fromEntries(['body','pose','composition','perspective'].map(role=>[role,graphNodeColor(role,true)])),{
  body:'#9CE4DA',pose:'#FFC28F',composition:'#D8C1FF',perspective:'#A9E58B',
 });
});
