import test from 'node:test';
import assert from 'node:assert/strict';
import { placeMasonry } from '../lib/masonry.mjs';

test('short cards pack below their column without shared row whitespace', () => {
  const result = placeMasonry(740, [400, 100, 250, 90, 120]);
  assert.equal(result.itemWidth, 240);
  assert.deepEqual(result.positions[3], {left:250, top:110});
  assert.deepEqual(result.positions[4], {left:250, top:210});
  assert.equal(result.height,400);
});
test('reflow after image load, failure, resize and appends never overlaps or reorders DOM', () => {
  for (const width of [320,740,1240]) for (const heights of [[64,64,64,64],[400,100,250,64],[400,100,64,64,510,80]]) {
    const result=placeMasonry(width,heights);
    result.positions.forEach((p,i)=>{
      assert(p.top >= (result.positions[i-1]?.top ?? 0));
      assert(p.left + result.itemWidth <= width + .01);
      for(let j=0;j<i;j++) if(result.positions[j].left===p.left) assert(p.top>=result.positions[j].top+heights[j]+10);
    });
  }
  assert.equal(placeMasonry(320,[]).height,0);
});
